const express = require("express");
const axios = require("axios");
const QRCode = require("qrcode");
const { Client, LocalAuth, Buttons } = require("whatsapp-web.js");
const fs = require("fs");
const path = require("path");

const app = express();
app.use(express.json({ limit: "1mb" }));

const adminToken = (process.env.TOBY_ADMIN_TOKEN || "").trim();
const backendBaseUrl = process.env.TOBY_BACKEND_URL || "http://127.0.0.1:8787";
const port = Number(process.env.TOBY_BRIDGE_PORT || 8788);
const sessionDir = path.join(process.cwd(), ".wwebjs_auth");
const dataDir = path.resolve(process.cwd(), "..", "data");
const pausedChatsPath = path.join(dataDir, "paused_chats.json");
const phoneCachePath = path.join(dataDir, "whatsapp_phone_cache.json");
const androidAppReminderStatePath = path.join(dataDir, "android_app_reminders.json");
const executablePath = process.env.PUPPETEER_EXECUTABLE_PATH || undefined;
process.on("unhandledRejection", (reason) => {
  console.error("Unhandled rejection:", reason);
});
process.on("uncaughtException", (error) => {
  console.error("Uncaught exception:", error);
});

let latestQr = null;
let bridgeState = {
  status: "starting",
  qr_available: false,
  last_event: "initializing"
};
let readyRecoveryTimer = null;
let initializeInFlight = false;
let initializeRetryTimer = null;
let initializeRetryAttempt = 0;
let lastInboundTime = Date.now(); // آخر مرة وصلت فيها رسالة inbound

// ─── Socket Health Probe ────────────────────────────────────────────────────
// كل 3 دقايق نتحقق إن الـ WhatsApp WebSocket لسه connected فعلاً
// لو الـ bridge قال ready لكن الـ socket منقطع → نعمل exit(1) وsystemd يعيد تشغيله
setInterval(async () => {
  if (bridgeState.status !== "ready") return;
  try {
    if (!client.pupPage || client.pupPage.isClosed()) {
      console.error("[socket-probe] pupPage closed while status=ready → exiting");
      process.exit(1);
    }
    const socketState = await client.pupPage.evaluate(() => {
      try {
        const Socket = window.require?.("WAWebSocketModel")?.Socket;
        return Socket?.state || "unknown";
      } catch (e) {
        return "error:" + e.message;
      }
    });
    if (socketState === "CONNECTED") {
      // كل شيء تمام
      return;
    }
    // الـ socket مش CONNECTED — ننتظر 30 ثانية بس بعدين نخرج
    console.warn(`[socket-probe] Socket state='${socketState}' (expected CONNECTED) → will exit in 30s`);
    setTimeout(() => {
      console.error("[socket-probe] Exit triggered after socket state mismatch");
      process.exit(1);
    }, 30000);
  } catch (err) {
    console.error("[socket-probe] probe error:", err.message);
  }
}, 3 * 60 * 1000); // كل 3 دقايق
// ──────────────────────────────────────────────────────────────────────────────
const INITIALIZE_RETRY_DELAYS_MS = [15000, 30000, 60000, 120000];
const UNSUPPORTED_MEDIA_REPLY = "الرسائل الصوتية والفيديو مش مدعومة حالياً. اكتب طلبك في رسالة نصية وأنا أساعدك.";
const CALL_REJECT_REPLY = "لأ، أنا مساعد ذكي مبعرفش أرد على المكالمات لسه. تقدر تبعتلي طلبك هنا كتابة وأنا هساعدك حالاً.";
const CUSTOMER_SERVICE_HANDOFF_TRIGGER = "تم تحويلك لخدمة العملاء الآن بنجاح.";
const CUSTOMER_SERVICE_HANDOFF_TRIGGER_LEGACY = "تم تحويلك لخدمة العملاء الآن بنجاح .";
const CUSTOMER_SERVICE_HANDOFF_END = "تم انتهاء المحادثة مع خدمة العملاء.";
const CUSTOMER_SERVICE_HANDOFF_MS = 5 * 60 * 1000;
const CUSTOMER_SERVICE_SURVEY_MS = Number(process.env.TOBY_SUPPORT_SURVEY_MS || String(10 * 60 * 1000));
const CUSTOMER_SERVICE_SURVEY_PENDING_MS = Number(
  process.env.TOBY_SUPPORT_SURVEY_PENDING_MS || String(24 * 60 * 60 * 1000)
);
const CUSTOMER_SERVICE_SURVEY_MESSAGE = [
  "رأيك يهمنا 🌟",
  "",
  "قيّم آخر محادثة مع خدمة العملاء من 1 إلى 5:",
  "1 = غير راضي",
  "5 = ممتاز",
  "",
  "ولو عندك ملاحظة قصيرة ابعتها بعد الرقم."
].join("\n");
const CUSTOMER_SERVICE_SURVEY_THANKS = "شكراً لتقييمك 🙏 رأيك بيساعدنا نحسّن الخدمة.";
const STOCKFLOW_PLAY_STORE_URL =
  "https://play.google.com/store/apps/details?id=com.mnagy.stockflowapp&pcampaignid=web_share";
const ANDROID_APP_REMINDER_MS = Number(
  process.env.TOBY_ANDROID_APP_REMINDER_MS || String(15 * 60 * 1000)
);
const ANDROID_APP_REMINDER_COOLDOWN_MS = Number(
  process.env.TOBY_ANDROID_APP_REMINDER_COOLDOWN_MS || String(48 * 60 * 60 * 1000)
);
const ANDROID_APP_REMINDER_CONTEXT_MAX_AGE_MS = Number(
  process.env.TOBY_ANDROID_APP_REMINDER_CONTEXT_MAX_AGE_MS || String(30 * 24 * 60 * 60 * 1000)
);
const IMAGE_REPLY_TIMEOUT_MS = Number(process.env.TOBY_IMAGE_REPLY_TIMEOUT_MS || "180000");
const supportHandoffTimers = new Map();
const supportSurveyTimers = new Map();
const supportSurveyPending = new Map();
const androidAppReminderTimers = new Map();
const androidAppReminderLastSent = new Map();
const processingChatIds = new Set();
const processingLockTimers = new Map();
// Image media (especially @lid) can need more than 90 seconds to become
// downloadable. Keep one inbound job protected while its retry loop runs.
const PROCESSING_LOCK_MS = Number(process.env.TOBY_PROCESSING_LOCK_MS || "300000");
const pausedChatIds = new Set();
const chatPhoneCache = new Map();
const botSentMessageIds = new Set();
const botSentFingerprints = new Set();
const autoRejectedCallIds = new Set();
const eagerImageDownloads = new Map();
const EAGER_IMAGE_DOWNLOAD_MS = Number(process.env.TOBY_EAGER_IMAGE_DOWNLOAD_MS || "150000");

/** تجنّب ردّ مزدوج لو `message` و `message_create` استقبلوا نفس الإشعار */
const inboundDedupeIds = new Set();
const inboundInflightIds = new Set();
const INBOUND_DEDUPE_LIMIT = 5000;

function getInboundDedupeId(message) {
  return (
    message?.id?._serialized ||
    `${message?.timestamp || ""}:${message?.from || ""}:${message?.type || ""}:${message?.body || ""}`
  );
}

function consumeInboundDedupe(message) {
  const id = getInboundDedupeId(message);
  if (!id) {
    return true;
  }
  if (inboundDedupeIds.has(id) || inboundInflightIds.has(id)) {
    return false;
  }
  inboundInflightIds.add(id);
  return id;
}

function finalizeInboundDedupe(dedupeToken) {
  if (!dedupeToken || dedupeToken === true) {
    return;
  }
  inboundInflightIds.delete(dedupeToken);
  inboundDedupeIds.add(dedupeToken);
  if (inboundDedupeIds.size > INBOUND_DEDUPE_LIMIT) {
    inboundDedupeIds.clear();
  }
}

function acquireProcessingLock(chatId) {
  const key = String(chatId || "").trim();
  if (!key || processingChatIds.has(key)) {
    return false;
  }
  processingChatIds.add(key);
  const existingTimer = processingLockTimers.get(key);
  if (existingTimer) {
    clearTimeout(existingTimer);
  }
  processingLockTimers.set(
    key,
    setTimeout(() => {
      console.warn(`[toby inbound] Force-releasing stuck processing lock for ${key}`);
      releaseProcessingLock(key);
    }, PROCESSING_LOCK_MS)
  );
  return true;
}

function releaseProcessingLock(chatId) {
  const key = String(chatId || "").trim();
  if (!key) {
    return;
  }
  stopTypingKeepAlive(key);
  processingChatIds.delete(key);
  const timer = processingLockTimers.get(key);
  if (timer) {
    clearTimeout(timer);
    processingLockTimers.delete(key);
  }
}

function rememberAutoRejectedCall(call) {
  const id =
    String(call?.id || "").trim() ||
    `${String(call?.from || "").trim()}:${call?.timestamp || ""}:${call?.isVideo ? "video" : "voice"}`;
  if (!id || id === "::voice" || id === "::video") {
    return true;
  }
  if (autoRejectedCallIds.has(id)) {
    return false;
  }
  autoRejectedCallIds.add(id);
  setTimeout(() => autoRejectedCallIds.delete(id), 5 * 60 * 1000);
  return true;
}

function isStatusBroadcastMessage(message) {
  const fromValue = String(message?.from || "").trim();
  const chatId = String(message?.id?.remote || "").trim();
  return fromValue === "status@broadcast" || chatId === "status@broadcast";
}

function isUnsupportedMediaMessage(message) {
  const messageType = String(message?.type || "").trim().toLowerCase();
  // الصور مسموح بيها (لتحميل إيصالات الدفع) — الباقي مش مدعوم
  return ["audio", "ptt", "voice", "video"].includes(messageType);
}

function isImageLikeMediaMessage(message) {
  const messageType = String(message?.type || "").trim().toLowerCase();
  const mimetype = String(message?.mimetype || "").trim().toLowerCase();
  return messageType === "image" || (messageType === "document" && mimetype.startsWith("image/"));
}

function chatIdDigits(chatId) {
  return String(chatId || "").trim().replace(/@(c\.us|lid)$/, "");
}

function isLidChatId(chatId) {
  return String(chatId || "").trim().endsWith("@lid");
}

function looksLikeEgyptianMobileDigits(digits) {
  const clean = String(digits || "").replace(/\D/g, "");
  return /^(201[0125]\d{8}|01[0125]\d{8})$/.test(clean);
}

function getReservedPhoneChatIds() {
  const raw = String(process.env.TOBY_RESERVED_PHONE_IDS || "").trim();
  const defaults = [];
  const fromEnv = raw
    ? raw.split(/[,\s;]+/).map((value) => {
        const cleaned = String(value || "").trim();
        if (!cleaned) {
          return "";
        }
        return cleaned.includes("@") ? cleaned : `${cleaned.replace(/\D/g, "")}@c.us`;
      })
    : [];
  return new Set([...defaults, ...fromEnv].filter(Boolean));
}

function isReservedPhoneChatId(phoneChatId) {
  const clean = String(phoneChatId || "").trim();
  if (!clean.endsWith("@c.us")) {
    return false;
  }
  return getReservedPhoneChatIds().has(clean);
}

function isValidLidPhoneMapping(lidChatId, phoneChatId) {
  const lidDigits = chatIdDigits(lidChatId);
  const phoneDigits = chatIdDigits(phoneChatId);
  if (!lidDigits || !phoneDigits || !isBackendPhoneId(phoneChatId)) {
    return false;
  }
  if (isReservedPhoneChatId(phoneChatId)) {
    return false;
  }
  // A stale cache often maps the LID numeric id to the same id @c.us.
  if (lidDigits === phoneDigits) {
    return false;
  }
  // LID ids are internal WhatsApp identifiers, not Egyptian mobiles.
  return looksLikeEgyptianMobileDigits(phoneDigits);
}

function sanitizePhoneCacheEntries() {
  let removed = 0;
  for (const [chatId, phoneId] of Array.from(chatPhoneCache.entries())) {
    if (isLidChatId(chatId) && !isValidLidPhoneMapping(chatId, phoneId)) {
      chatPhoneCache.delete(chatId);
      removed += 1;
    }
  }
  if (removed > 0) {
    console.warn(`[phone-cache] Removed ${removed} invalid LID mapping(s) from cache`);
    savePhoneCache();
  }
}

/**
 * يحول LID (مثل 71240622575698@lid) لـ phone-based chat ID (مثل 201234567890@c.us)
 * ده مهم لتحميل الصور من @lid chats لأن الـ media metadata مش متزامن في الـ web client
 * للـ @lid chats. بنستخدم `client.getContactLidAndPhone` الموجود في المكتبة.
 */
async function resolveLidToPhoneChatId(client, lidChatId) {
  const cleanLid = String(lidChatId || "").trim();
  if (!cleanLid.endsWith("@lid")) {
    return "";
  }
  if (typeof client.getContactLidAndPhone !== "function") {
    return "";
  }
  try {
    const result = await client.getContactLidAndPhone([cleanLid]);
    if (Array.isArray(result) && result.length > 0) {
      const entry = result[0] || {};
      const pn = entry.pn || entry.phone || "";
      if (pn && String(pn).endsWith("@c.us")) {
        const resolvedPhoneChatId = String(pn);
        if (!isValidLidPhoneMapping(cleanLid, resolvedPhoneChatId)) {
          console.warn(
            `[resolveLidToPhoneChatId] Rejecting implausible mapping ${cleanLid} -> ${resolvedPhoneChatId}`
          );
          return "";
        }
        // Keep the phone mapping in sync.  A stale @lid cache entry can point
        // to the numeric LID itself, which splits the backend session and also
        // makes subsequent media lookups use the wrong chat.
        rememberPhoneForChat(cleanLid, resolvedPhoneChatId);
        return resolvedPhoneChatId;
      }
    }
  } catch (err) {
    console.warn(
      `[resolveLidToPhoneChatId] failed for ${cleanLid}:`,
      String(err.message || err).slice(0, 160)
    );
  }
  return "";
}

/**
 * يحمل الصورة مباشرة من الـ underlying WhatsApp store باستخدام pupPage.evaluate.
 * ده workaround للـ @lid chats اللي الـ message object فيها detached ومش كامل.
 * بنبحث عن الرسالة في الـ Chat model للـ phone-based chat ID.
 */
async function downloadMediaDirect(client, messageId, alternateChatId, hintTimestamp) {
  if (!client?.pupPage || !messageId) {
    return null;
  }
  const result = await client.pupPage.evaluate(
    async (msgId, altChatId, hintTs) => {
      const getMediaField = (m, k) => {
        if (!m) return undefined;
        if (m[k] !== undefined && m[k] !== null) return m[k];
        if (m.mediaData && m.mediaData[k] !== undefined && m.mediaData[k] !== null) return m.mediaData[k];
        return undefined;
      };

      const tryFromCollections = (id) => {
        try {
          const Msg = window.require('WAWebCollections').Msg;
          return Msg.get(id) ||
            (Msg.getMessagesById && (Msg.getMessagesById([id])?.messages?.[0]));
        } catch (e) {
          return null;
        }
      };

      const isImageLike = (candidate) => {
        const candidateType = String(candidate?.type || '').toLowerCase();
        const candidateMimetype = String(getMediaField(candidate, 'mimetype') || candidate?.mimetype || '').toLowerCase();
        return candidateType === 'image' ||
          (candidateType === 'document' && candidateMimetype.startsWith('image/'));
      };
      const isDownloadableMedia = (candidate) => {
        const dp = getMediaField(candidate, 'directPath');
        const mk = getMediaField(candidate, 'mediaKey');
        return Boolean(candidate && dp && mk);
      };

      // جرب الـ message ID نفسه أولاً (قد يكون في store تاني)
      let msg = tryFromCollections(msgId);
      let usedChat = '';

      if ((!msg || !isDownloadableMedia(msg)) && altChatId) {
        try {
          const detachedMsg = msg;
          msg = null;
          const Chat = window.require('WAWebCollections').Chat;
          const chat = Chat.get(altChatId) ||
            (window.WWebJS?.getChat
              ? await window.WWebJS.getChat(altChatId, { getAsModel: false })
              : null);
          if (chat) {
            usedChat = altChatId;
            const allMsgs = await chat.getMessages
              ? chat.getMessages({ count: 200 })
              : (chat.msgs && Array.from(chat.msgs.models || []));
            const list = Array.isArray(allMsgs) ? allMsgs : [];

            for (const m of list) {
              if (m?.id?._serialized === msgId) {
                msg = m;
                break;
              }
            }

            if (!msg || !isDownloadableMedia(msg)) {
              const orig = detachedMsg || tryFromCollections(msgId);
              const origTs = hintTs || (orig && (orig.t || orig.timestamp));
              if (origTs) {
                const windowSec = 180;
                const candidates = list
                  .filter((m) => isImageLike(m))
                  .filter((m) => {
                    const t = m.t || m.timestamp || 0;
                    return Math.abs((t || 0) - origTs) <= windowSec;
                  })
                  .sort((a, b) => {
                    const bReady = Number(isDownloadableMedia(b));
                    const aReady = Number(isDownloadableMedia(a));
                    if (bReady !== aReady) return bReady - aReady;
                    return Math.abs((a.t||a.timestamp||0) - origTs) -
                      Math.abs((b.t||b.timestamp||0) - origTs);
                  });
                if (candidates.length > 0) {
                  msg = candidates[0];
                  usedChat = `${altChatId}|ts_match:${msg.t || msg.timestamp}`;
                }
              }
            }
          }
          if (!msg && detachedMsg) {
            msg = detachedMsg;
          }
        } catch (e) {
          // ignore lookup error and proceed
        }
      }

      if (!msg) {
        // DOM Fallback: inspect document directly for recently received images
        try {
          const domImages = Array.from(document.querySelectorAll('img[src^="blob:"], img[src^="data:image"]'));
          if (domImages.length > 0) {
            const lastImg = domImages[domImages.length - 1];
            if (lastImg.src.startsWith('data:image')) {
              const b64 = lastImg.src.split(',')[1];
              return { data: b64, mimetype: 'image/jpeg', filename: 'image.jpg', usedChat: 'dom_data_url' };
            }
            const resp = await fetch(lastImg.src);
            const blob = await resp.blob();
            const reader = new FileReader();
            const b64 = await new Promise((res) => {
              reader.onloadend = () => {
                const str = String(reader.result || '');
                res(str.includes(',') ? str.split(',')[1] : str);
              };
              reader.readAsDataURL(blob);
            });
            if (b64 && b64.length > 200) {
              return { data: b64, mimetype: blob.type || 'image/jpeg', filename: 'image.jpg', usedChat: 'dom_blob' };
            }
          }
        } catch (_) {}
        return { error: 'message_not_found_in_store' };
      }

      const dp = getMediaField(msg, 'directPath');
      const mk = getMediaField(msg, 'mediaKey');
      const encFh = getMediaField(msg, 'encFilehash');
      const fh = getMediaField(msg, 'filehash');
      const mkTs = getMediaField(msg, 'mediaKeyTimestamp');
      const mime = getMediaField(msg, 'mimetype') || msg.mimetype || 'image/jpeg';
      const sz = getMediaField(msg, 'size') || msg.size || 0;
      const tp = getMediaField(msg, 'type') || msg.type || 'image';

      if (!dp || !mk) {
        const sleepInner = (ms) => new Promise((r) => setTimeout(r, ms));
        try {
          if (typeof msg.downloadMedia === 'function') {
            await msg.downloadMedia({ downloadEvenIfExpensive: true, rmrReason: 1 });
          }
        } catch (_) {}
        await sleepInner(1500);
      }

      const finalDp = getMediaField(msg, 'directPath');
      const finalMk = getMediaField(msg, 'mediaKey');

      if (finalDp && finalMk) {
        try {
          const mockQpl = {
            addAnnotations: function () { return this; },
            addPoint: function () { return this; },
          };
          const decryptedMedia = await window
            .require('WAWebDownloadManager')
            .downloadManager.downloadAndMaybeDecrypt({
              directPath: finalDp,
              encFilehash: getMediaField(msg, 'encFilehash') || encFh,
              filehash: getMediaField(msg, 'filehash') || fh,
              mediaKey: finalMk,
              mediaKeyTimestamp: getMediaField(msg, 'mediaKeyTimestamp') || mkTs,
              type: tp,
              signal: new AbortController().signal,
              downloadQpl: mockQpl,
            });
          const data = await window.WWebJS.arrayBufferToBase64Async(decryptedMedia);
          return {
            data,
            mimetype: mime,
            filename: msg.filename || 'receipt.jpg',
            filesize: sz,
            usedChat,
          };
        } catch (e) {
          // fallback to DOM
        }
      }

      // DOM fallback if decrypt failed or directPath missing
      try {
        const domImages = Array.from(document.querySelectorAll('img[src^="blob:"], img[src^="data:image"]'));
        if (domImages.length > 0) {
          const lastImg = domImages[domImages.length - 1];
          if (lastImg.src.startsWith('data:image')) {
            const b64 = lastImg.src.split(',')[1];
            return { data: b64, mimetype: 'image/jpeg', filename: 'image.jpg', usedChat: 'dom_data_url' };
          }
          const resp = await fetch(lastImg.src);
          const blob = await resp.blob();
          const reader = new FileReader();
          const b64 = await new Promise((res) => {
            reader.onloadend = () => {
              const str = String(reader.result || '');
              res(str.includes(',') ? str.split(',')[1] : str);
            };
            reader.readAsDataURL(blob);
          });
          if (b64 && b64.length > 200) {
            return { data: b64, mimetype: blob.type || 'image/jpeg', filename: 'image.jpg', usedChat: 'dom_blob' };
          }
        }
      } catch (_) {}

      return { error: 'media_download_failed_all_methods', usedChat };
    },
    messageId,
    alternateChatId || '',
    hintTimestamp || 0
  );
  if (!result || result.error) {
    const errStr = result ? result.error : 'no_result';
    const diagStr = result && result.diag ? JSON.stringify(result.diag) : 'no-diag';
    const usedChatStr = result && result.usedChat ? result.usedChat : 'none';
    console.warn(
      `[downloadMediaDirect] failed for ${messageId} via ${alternateChatId || 'n/a'}:`,
      `error=${errStr}`,
      `diag=${diagStr}`,
      `usedChat=${usedChatStr}`
    );
    return null;
  }
  return {
    data: result.data,
    mimetype: result.mimetype || 'image/jpeg',
    filename: result.filename || '',
    filesize: result.filesize || 0,
  };
}

async function pollMessageMediaById(client, messageId, hintTimestamp, maxWaitMs) {
  if (!client?.pupPage || !messageId) {
    return null;
  }
  const deadline = Date.now() + Math.max(10000, Number(maxWaitMs || EAGER_IMAGE_DOWNLOAD_MS));
  const pollMs = 2000;
  while (Date.now() < deadline) {
    const result = await client.pupPage.evaluate(async (msgId, hintTs) => {
      const sleepInner = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
      const getMsg = async () => {
        try {
          const Msg = window.require('WAWebCollections').Msg;
          let msg = Msg.get(msgId);
          if (!msg && Msg.getMessagesById) {
            const batch = await Msg.getMessagesById([msgId]);
            msg = batch?.messages?.[0];
          }
          return msg || null;
        } catch (e) {
          return null;
        }
      };

      let msg = await getMsg();
      if (!msg) {
        return { status: 'no_msg' };
      }

      if (!msg.mediaData) {
        try {
          await msg.downloadMedia?.({ downloadEvenIfExpensive: true, rmrReason: 1 });
        } catch (_) {}
        await sleepInner(1200);
        msg = await getMsg();
      }
      if (!msg || !msg.mediaData) {
        return {
          status: 'no_media_data',
          hasDirectPath: Boolean(msg && msg.directPath),
          hasMediaKey: Boolean(msg && msg.mediaKey),
        };
      }

      const stage = String(msg.mediaData.mediaStage || '').toUpperCase();
      if (stage === 'REUPLOADING') {
        return { status: 'reuploading' };
      }
      if (stage && stage !== 'RESOLVED') {
        try {
          await msg.downloadMedia({ downloadEvenIfExpensive: true, rmrReason: 1 });
        } catch (_) {}
        await sleepInner(1500);
        msg = await getMsg();
      }
      if (!msg || !msg.directPath || !msg.mediaKey) {
        return {
          status: 'missing_keys',
          stage: String((msg && msg.mediaData && msg.mediaData.mediaStage) || ''),
        };
      }

      try {
        const mockQpl = {
          addAnnotations: function () { return this; },
          addPoint: function () { return this; },
        };
        const decryptedMedia = await window
          .require('WAWebDownloadManager')
          .downloadManager.downloadAndMaybeDecrypt({
            directPath: msg.directPath,
            encFilehash: msg.encFilehash,
            filehash: msg.filehash,
            mediaKey: msg.mediaKey,
            mediaKeyTimestamp: msg.mediaKeyTimestamp,
            type: msg.type,
            signal: new AbortController().signal,
            downloadQpl: mockQpl,
          });
        const data = await window.WWebJS.arrayBufferToBase64Async(decryptedMedia);
        return {
          status: 'ok',
          data,
          mimetype: msg.mimetype || 'image/jpeg',
        };
      } catch (e) {
        return { status: 'decrypt_failed', error: String(e && e.message ? e.message : e) };
      }
    }, messageId, Number(hintTimestamp || 0));

    if (result?.status === 'ok' && result.data) {
      return { data: result.data, mimetype: result.mimetype || 'image/jpeg' };
    }
    await sleep(pollMs);
  }
  return null;
}

function startEagerImageDownload(message) {
  const msgId = String(message?.id?._serialized || '').trim();
  if (!msgId || eagerImageDownloads.has(msgId)) {
    return eagerImageDownloads.get(msgId);
  }

  const task = (async () => {
  try {
    for (let attempt = 1; attempt <= 20; attempt++) {
      try {
        if (typeof message.reload === 'function') {
          await message.reload();
        }
      } catch (_) {}
      try {
        const media = await message.downloadMedia({
          downloadEvenIfExpensive: true,
          rmrReason: 1,
        });
        if (media?.data) {
          console.log(`[image-eager] download succeeded on attempt ${attempt} for ${msgId}`);
          return { data: media.data, mimetype: media.mimetype || 'image/jpeg' };
        }
      } catch (error) {
        if (attempt === 1 || attempt % 5 === 0) {
          console.warn(
            `[image-eager] attempt ${attempt} failed for ${msgId}:`,
            String(error?.message || error).slice(0, 160)
          );
        }
      }
      await sleep(attempt <= 3 ? 1000 : 2500);
    }

    const polled = await pollMessageMediaById(
      client,
      msgId,
      message.timestamp,
      EAGER_IMAGE_DOWNLOAD_MS
    );
    if (polled?.data) {
      console.log(`[image-eager] poll succeeded for ${msgId}`);
      return polled;
    }
  } catch (error) {
    console.warn(`[image-eager] failed for ${msgId}:`, String(error?.message || error).slice(0, 160));
  }
  return null;
  })();

  eagerImageDownloads.set(msgId, task);
  task.finally(() => {
    setTimeout(() => eagerImageDownloads.delete(msgId), 10 * 60 * 1000);
  });
  return task;
}

async function consumeEagerImageDownload(messageId, waitMs) {
  const msgId = String(messageId || '').trim();
  if (!msgId) {
    return null;
  }
  const pending = eagerImageDownloads.get(msgId);
  if (!pending) {
    return null;
  }
  try {
    return await withTimeout(pending, Number(waitMs || EAGER_IMAGE_DOWNLOAD_MS), 'eager_image_download');
  } catch (error) {
    console.warn(`[image-eager] wait timed out for ${msgId}:`, String(error?.message || error).slice(0, 120));
    return null;
  }
}

function normalizeMessageText(text) {
  return String(text || "").replace(/\s+/g, " ").trim();
}

function buildOutgoingFingerprint(to, text) {
  return `${String(to || "").trim()}::${normalizeMessageText(text).slice(0, 500)}`;
}

function rememberBotOutgoingFingerprint(to, text) {
  const fingerprint = buildOutgoingFingerprint(to, text);
  if (fingerprint !== "::") {
    botSentFingerprints.add(fingerprint);
    setTimeout(() => botSentFingerprints.delete(fingerprint), 120000);
  }
}

function rememberBotSentMessage(to, text, sentMessage) {
  const messageId = sentMessage?.id?._serialized;
  if (messageId) {
    botSentMessageIds.add(messageId);
    setTimeout(() => botSentMessageIds.delete(messageId), 120000);
  }
  rememberBotOutgoingFingerprint(to, text);
}

function isKnownBotSentMessage(message, chatId) {
  const messageId = message?.id?._serialized;
  if (messageId && botSentMessageIds.has(messageId)) {
    botSentMessageIds.delete(messageId);
    return true;
  }
  const fingerprint = buildOutgoingFingerprint(chatId, message?.body || "");
  if (botSentFingerprints.has(fingerprint)) {
    botSentFingerprints.delete(fingerprint);
    return true;
  }
  return false;
}

function ensureDataDir() {
  try {
    fs.mkdirSync(dataDir, { recursive: true });
  } catch (_) {
  }
}

function loadPausedChats() {
  try {
    if (!fs.existsSync(pausedChatsPath)) {
      return;
    }
    const payload = JSON.parse(fs.readFileSync(pausedChatsPath, "utf8"));
    const items = Array.isArray(payload?.chat_ids) ? payload.chat_ids : [];
    pausedChatIds.clear();
    for (const item of items) {
      const chatId = String(item || "").trim();
      if (chatId) {
        pausedChatIds.add(chatId);
      }
    }
  } catch (error) {
    console.error("Failed to load paused chats:", error.message);
  }
}

function savePausedChats() {
  try {
    ensureDataDir();
    fs.writeFileSync(
      pausedChatsPath,
      JSON.stringify({ chat_ids: Array.from(pausedChatIds).sort() }, null, 2),
      "utf8"
    );
  } catch (error) {
    console.error("Failed to save paused chats:", error.message);
  }
}

function isBackendPhoneId(value) {
  const cleaned = String(value || "").trim();
  if (!cleaned.endsWith("@c.us")) {
    return false;
  }
  const digits = cleaned.replace("@c.us", "");
  return /^\d{7,15}$/.test(digits);
}

function loadPhoneCache() {
  try {
    if (!fs.existsSync(phoneCachePath)) {
      return;
    }
    const payload = JSON.parse(fs.readFileSync(phoneCachePath, "utf8"));
    const items = payload?.chat_to_phone && typeof payload.chat_to_phone === "object"
      ? payload.chat_to_phone
      : {};
    chatPhoneCache.clear();
    for (const [chatId, phoneId] of Object.entries(items)) {
      const cleanChatId = String(chatId || "").trim();
      const cleanPhoneId = String(phoneId || "").trim();
      if (!cleanChatId || !isBackendPhoneId(cleanPhoneId)) {
        continue;
      }
      if (isLidChatId(cleanChatId) && !isValidLidPhoneMapping(cleanChatId, cleanPhoneId)) {
        continue;
      }
      chatPhoneCache.set(cleanChatId, cleanPhoneId);
    }
    sanitizePhoneCacheEntries();
  } catch (error) {
    console.error("Failed to load WhatsApp phone cache:", error.message);
  }
}

function savePhoneCache() {
  try {
    ensureDataDir();
    const entries = Array.from(chatPhoneCache.entries()).sort(([a], [b]) => a.localeCompare(b));
    fs.writeFileSync(
      phoneCachePath,
      JSON.stringify({ chat_to_phone: Object.fromEntries(entries) }, null, 2),
      "utf8"
    );
  } catch (error) {
    console.error("Failed to save WhatsApp phone cache:", error.message);
  }
}

function loadAndroidAppReminderState() {
  try {
    if (!fs.existsSync(androidAppReminderStatePath)) {
      return;
    }
    const payload = JSON.parse(fs.readFileSync(androidAppReminderStatePath, "utf8"));
    const items =
      payload?.last_sent_at && typeof payload.last_sent_at === "object"
        ? payload.last_sent_at
        : {};
    androidAppReminderLastSent.clear();
    for (const [chatId, value] of Object.entries(items)) {
      const cleanChatId = String(chatId || "").trim();
      const timestamp = typeof value === "number" ? value : Date.parse(String(value || ""));
      if (cleanChatId && Number.isFinite(timestamp) && timestamp > 0) {
        androidAppReminderLastSent.set(cleanChatId, timestamp);
      }
    }
  } catch (error) {
    console.error("Failed to load Android app reminder state:", error.message);
  }
}

function saveAndroidAppReminderState() {
  try {
    ensureDataDir();
    const cutoff = Date.now() - Math.max(ANDROID_APP_REMINDER_COOLDOWN_MS * 3, 7 * 24 * 60 * 60 * 1000);
    const entries = Array.from(androidAppReminderLastSent.entries())
      .filter(([_chatId, timestamp]) => Number.isFinite(timestamp) && timestamp >= cutoff)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([chatId, timestamp]) => [chatId, new Date(timestamp).toISOString()]);
    fs.writeFileSync(
      androidAppReminderStatePath,
      JSON.stringify({ last_sent_at: Object.fromEntries(entries) }, null, 2),
      "utf8"
    );
  } catch (error) {
    console.error("Failed to save Android app reminder state:", error.message);
  }
}

function rememberPhoneForChat(chatId, phoneId) {
  const cleanChatId = String(chatId || "").trim();
  const cleanPhoneId = String(phoneId || "").trim();
  if (!cleanChatId || !isBackendPhoneId(cleanPhoneId)) {
    return;
  }
  if (isLidChatId(cleanChatId) && !isValidLidPhoneMapping(cleanChatId, cleanPhoneId)) {
    if (chatPhoneCache.has(cleanChatId)) {
      chatPhoneCache.delete(cleanChatId);
      savePhoneCache();
    }
    return;
  }
  if (chatPhoneCache.get(cleanChatId) === cleanPhoneId) {
    return;
  }
  chatPhoneCache.set(cleanChatId, cleanPhoneId);
  savePhoneCache();
}

function getCachedPhoneForChat(chatId) {
  return chatPhoneCache.get(String(chatId || "").trim()) || "";
}

function addPauseKeyVariants(keys, value) {
  const cleaned = String(value || "").trim();
  if (!cleaned) {
    return;
  }
  keys.add(cleaned);

  let base = cleaned;
  if (cleaned.endsWith("@c.us")) {
    base = cleaned.replace("@c.us", "");
    keys.add(base);
  } else if (cleaned.endsWith("@lid")) {
    base = cleaned.replace("@lid", "");
    keys.add(base);
  }

  if (!/^\d+$/.test(base)) {
    return;
  }
  keys.add(base);

  let localPhone = "";
  let intlPhone = "";
  if (/^01[0125]\d{8}$/.test(base)) {
    localPhone = base;
    intlPhone = `20${base.slice(1)}`;
  } else if (/^201[0125]\d{8}$/.test(base)) {
    intlPhone = base;
    localPhone = `0${base.slice(2)}`;
  }

  for (const phone of [localPhone, intlPhone]) {
    if (!phone) {
      continue;
    }
    keys.add(phone);
    keys.add(`${phone}@c.us`);
  }
}

function buildPauseKeys(chatId, phoneId) {
  const keys = new Set();
  for (const value of [chatId, phoneId]) {
    addPauseKeyVariants(keys, value);
  }
  return Array.from(keys);
}

function normalizeManualChatId(value) {
  const cleaned = String(value || "").trim();
  if (!cleaned) {
    return "";
  }
  if (cleaned.includes("@")) {
    return cleaned;
  }
  const digits = cleaned.replace(/\D/g, "");
  if (digits.length >= 7) {
    return `${digits}@c.us`;
  }
  return cleaned;
}

function isChatPaused(chatId, phoneId) {
  return buildPauseKeys(chatId, phoneId).some((key) => pausedChatIds.has(key));
}

function pauseChat(chatId, phoneId) {
  clearAndroidAppReminder(chatId);
  for (const key of buildPauseKeys(chatId, phoneId)) {
    pausedChatIds.add(key);
  }
  savePausedChats();
}

function resumeChat(chatId, phoneId) {
  for (const key of buildPauseKeys(chatId, phoneId)) {
    pausedChatIds.delete(key);
  }
  savePausedChats();
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function withTimeout(promise, ms, label) {
  let timer;
  const timeoutPromise = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(`${label || "operation"}_timeout`)), ms);
  });
  return Promise.race([promise, timeoutPromise]).finally(() => clearTimeout(timer));
}

function clearInitializeRetry() {
  if (initializeRetryTimer) {
    clearTimeout(initializeRetryTimer);
    initializeRetryTimer = null;
  }
  initializeRetryAttempt = 0;
}

function scheduleInitializeRetry(reason) {
  if (initializeRetryTimer || initializeInFlight) {
    return;
  }
  const delayIndex = Math.min(initializeRetryAttempt, INITIALIZE_RETRY_DELAYS_MS.length - 1);
  const delayMs = INITIALIZE_RETRY_DELAYS_MS[delayIndex];
  initializeRetryAttempt += 1;
  initializeRetryTimer = setTimeout(async () => {
    initializeRetryTimer = null;
    try {
      await restartClient(`Automatic WhatsApp recovery after ${reason}`);
      initializeRetryAttempt = 0;
    } catch (error) {
      console.error("Automatic WhatsApp recovery failed:", error.message);
      await pushState({
        status: "initialization_failed",
        qr_available: false,
        last_event: `Automatic recovery failed: ${error.message}`
      });
      scheduleInitializeRetry(error.message);
    }
  }, delayMs);
}

async function handleInitializationFailure(error) {
  const message = error?.message || "unknown initialization error";
  console.error("Failed to initialize WhatsApp client:", message);
  await pushState({
    status: "initialization_failed",
    qr_available: false,
    last_event: `WhatsApp initialization failed: ${message}`
  });
  scheduleInitializeRetry(message);
}

const TYPING_REFRESH_MS = 20000;
const rawTypingEnv = String(process.env.TOBY_TYPING_ENABLED ?? "1").trim().toLowerCase();
const TYPING_ENABLED = !["0", "false", "no", "off"].includes(rawTypingEnv);
const TYPING_CHAT_TIMEOUT_MS = Number(process.env.TOBY_TYPING_CHAT_TIMEOUT_MS || "2500");
const SEND_MESSAGE_TIMEOUT_MS = Number(process.env.TOBY_SEND_MESSAGE_TIMEOUT_MS || "30000");
const typingKeepAliveTimers = new Map();
const typingChatCache = new Map();

async function markChatSeenAndPresent(to, sourceMessage = null) {
  try {
    if (client) {
      await client.sendPresenceAvailable().catch(() => {});
    }
    if (sourceMessage && typeof sourceMessage.getChat === "function") {
      const chat = await sourceMessage.getChat().catch(() => null);
      if (chat && typeof chat.sendSeen === "function") {
        await chat.sendSeen().catch(() => {});
      }
    } else if (client?.pupPage && to) {
      await client.pupPage.evaluate(async (chatIdStr) => {
        try {
          const WidFactory = window.require("WAWebWidFactory") || window.require("WidFactory");
          const createWid = WidFactory.createWid || WidFactory.createWidLegacy;
          const chatId = createWid(chatIdStr);
          const Chat = window.require("WAWebChatCollection")?.get?.(chatId);
          if (Chat && window.require("WAWebSendSeen")?.sendSeen) {
            await window.require("WAWebSendSeen").sendSeen(Chat);
          }
        } catch (_) {}
      }, String(to).trim()).catch(() => {});
    }
  } catch (_) {}
}

function computeReadingDelayMs(text) {
  return 1000 + Math.floor(Math.random() * 1200);
}

function stopTypingKeepAlive(chatKey) {
  const key = String(chatKey || "").trim();
  if (!key) {
    return;
  }
  const timer = typingKeepAliveTimers.get(key);
  if (timer) {
    clearInterval(timer);
    typingKeepAliveTimers.delete(key);
  }
  typingChatCache.delete(key);
}

async function setChatTypingState(to, state) {
  if (!client?.pupPage) {
    return { ok: false, error: "no_pup_page" };
  }
  try {
    const result = await client.pupPage.evaluate(async (chatIdStr, chatState) => {
      try {
        const WidFactory = window.require("WAWebWidFactory") || window.require("WidFactory");
        const createWid = WidFactory.createWid || WidFactory.createWidLegacy;
        const chatId = createWid(chatIdStr);
        const ChatState = window.require("WAWebChatStateBridge") || window.require("ChatState");
        if (chatState === "typing") {
          if (ChatState.sendChatStateComposing) {
            await ChatState.sendChatStateComposing(chatId);
          } else if (ChatState.sendChatStateTyping) {
            await ChatState.sendChatStateTyping(chatId);
          } else {
            throw new Error("No sendChatStateComposing or sendChatStateTyping method");
          }
        } else {
          if (ChatState.sendChatStatePaused) {
            await ChatState.sendChatStatePaused(chatId);
          } else {
            throw new Error("No sendChatStatePaused method");
          }
        }
        return { ok: true, method: "direct_bridge" };
      } catch (err) {
        return { ok: false, error: err.message || String(err) };
      }
    }, String(to).trim(), state);
    return result;
  } catch (err) {
    return { ok: false, error: err.message || String(err) };
  }
}

async function refreshTypingState(chatKey, to, sourceMessage = null) {
  if (!TYPING_ENABLED) {
    return;
  }
  try {
    const result = await setChatTypingState(to, "typing");
    if (!result.ok) {
      console.warn("[typing diag] setChatTypingState typing failed for", to, ":", result.error);
    } else {
      console.log("[typing diag] setChatTypingState typing success for", to);
    }
  } catch (error) {
    console.warn("Failed to refresh typing state:", error.message);
  }
}

async function startTypingKeepAlive(to, sourceMessage = null) {
  if (!TYPING_ENABLED) {
    return;
  }
  const chatKey = String(to || "").trim();
  if (!chatKey) {
    return;
  }
  stopTypingKeepAlive(chatKey);
  await refreshTypingState(chatKey, to, sourceMessage);
  const timer = setInterval(() => {
    refreshTypingState(chatKey, to, sourceMessage);
  }, TYPING_REFRESH_MS);
  typingKeepAliveTimers.set(chatKey, timer);
}

function computeTypingDelayMs(text) {
  const length = normalizeMessageText(text).length;
  if (!length) {
    return 0;
  }
  const ratio = Math.min(length / 140, 1);
  const baseMs = 1200 + Math.round(ratio * 1300);
  // Add realistic human jitter (0.80x to 1.20x plus random delta)
  const jitterFactor = 0.8 + (Math.random() * 0.4);
  const extraNoise = Math.floor(Math.random() * 300) - 150;
  const calculated = Math.round(baseMs * jitterFactor) + extraNoise;
  return Math.max(600, Math.min(4500, calculated));
}

async function startTypingIndicator(to, sourceMessage = null) {
  if (!TYPING_ENABLED) {
    return null;
  }
  try {
    const result = await setChatTypingState(to, "typing");
    if (!result.ok) {
      console.warn("[typing diag] startTypingIndicator failed for", to, ":", result.error);
    } else {
      console.log("[typing diag] startTypingIndicator success for", to);
    }
    return to;
  } catch (error) {
    console.warn("Failed to start typing state:", error.message);
  }
  return null;
}

async function stopTypingIndicator(typingChat, to, sourceMessage = null) {
  if (!TYPING_ENABLED) {
    return;
  }
  try {
    const target = typingChat || to;
    const result = await setChatTypingState(target, "paused");
    if (!result.ok) {
      console.warn("[typing diag] stopTypingIndicator failed for", target, ":", result.error);
    } else {
      console.log("[typing diag] stopTypingIndicator success for", target);
    }
  } catch (error) {
    console.warn("Failed to clear typing state:", error.message);
  }
}

function getMessageChatId(message) {
  if (message?.fromMe) {
    return String(message?.to || message?.id?.remote || "").trim();
  }
  return String(message?.from || message?.id?.remote || "").trim();
}

/**
 * رقم الهاتف/المعرّف لطلب الباك اند — بدون تعطيل إرسال الردود.
 * واتساب حالياً قد يمرّر المحادثة كـ @lid؛ جزء قبل @lid ليس شرطًا رقم تليفون،
 * فتحويله يدوياً إلى @c.us كان يكسّر sendMessage وبيطلع "No LID for user".
 */
async function resolvePhoneFromContact(message, chatId) {
  /** getContact() أحياناً يعلق أو يرفض؛ نفرض مهلة صغيرة بدل ما نقفل المعالجة بالكامل */
  const ms = Number(process.env.TOBY_GET_CONTACT_MS || "1200");
  try {
    const contactPromise = message.getContact();
    const deadline = new Promise((_, rej) =>
      setTimeout(() => rej(new Error("getContact_timeout")), ms)
    );
    const contact = await Promise.race([contactPromise, deadline]);
    if (contact && contact.number && contact.number.length >= 7) {
      const resolvedPhone = `${contact.number}@c.us`;
      if (!isLidChatId(chatId) || isValidLidPhoneMapping(chatId, resolvedPhone)) {
        rememberPhoneForChat(chatId, resolvedPhone);
        return resolvedPhone;
      }
    }
    if (
      contact &&
      contact.id &&
      contact.id._serialized &&
      contact.id._serialized.endsWith("@c.us")
    ) {
      const user = contact.id._serialized.replace("@c.us", "");
      if (/^\d+$/.test(user) && user.length <= 15) {
        const resolvedPhone = contact.id._serialized;
        if (!isLidChatId(chatId) || isValidLidPhoneMapping(chatId, resolvedPhone)) {
          rememberPhoneForChat(chatId, resolvedPhone);
          return resolvedPhone;
        }
      }
    }
  } catch (_) {
    // Fallback — لا نعلق طلب الإرسال
  }
  return "";
}

async function resolvePhoneForBackend(message, chatId) {
  const raw = String(chatId || "").trim();
  if (raw.endsWith("@c.us")) {
    rememberPhoneForChat(raw, raw);
    return raw;
  }

  // For @lid chats, prefer the live contact lookup over stale cache entries.
  // A bad cache (e.g. mapping many LIDs to the admin phone) breaks receipt OCR.
  if (isLidChatId(raw)) {
    const contactPhone = await resolvePhoneFromContact(message, raw);
    if (contactPhone) {
      return contactPhone;
    }
    try {
      const resolvedLidPhone = await resolveLidToPhoneChatId(client, raw);
      if (resolvedLidPhone) {
        return resolvedLidPhone;
      }
    } catch (_) {
      // Keep trying fallbacks below.
    }
    const cachedPhoneId = getCachedPhoneForChat(raw);
    if (cachedPhoneId && isValidLidPhoneMapping(raw, cachedPhoneId)) {
      return cachedPhoneId;
    }
    if (cachedPhoneId) {
      chatPhoneCache.delete(raw);
      savePhoneCache();
    }
    return raw;
  }

  const cachedPhoneId = getCachedPhoneForChat(raw);
  if (cachedPhoneId) {
    return cachedPhoneId;
  }

  const contactPhone = await resolvePhoneFromContact(message, raw);
  if (contactPhone) {
    return contactPhone;
  }

  return raw;
}

async function notifyBackendSupportHandoff(endpoint, phone) {
  await axios.post(
    `${backendBaseUrl}${endpoint}`,
    { phone },
    {
      headers: {
        "X-Bridge-Token": adminToken
      },
      timeout: 15000
    }
  );
}

function normalizeArabicAdminCommand(text) {
  return normalizeMessageText(text)
    .replace(/[إأآ]/g, "ا")
    .replace(/ى/g, "ي")
    .replace(/ة/g, "ه")
    .replace(/[.?!،]/g, "")
    .trim();
}

function extractAdminCompanyLinkName(messageText) {
  const normalized = normalizeMessageText(messageText);
  const match = normalized.match(
    /^تم\s+التعرف\s+عل[ىي]\s+الرقم\s+(?:ك(?:ـ)?\s*(?:شركة|شركه)?|ب[إا]سم\s+(?:شركة|شركه)?)\s+(.+)$/i
  );
  return match ? match[1].trim() : "";
}

function isAdminCompanyUnlinkCommand(messageText) {
  const normalized = normalizeArabicAdminCommand(messageText);
  return (
    /^(?:احذف|حذف|امسح|مسح)\s+اسم\s+الشركه(?:\s+من\s+قا(?:عده|عه)\s+البيانات)?$/.test(normalized) ||
    /^(?:احذف|حذف|امسح|مسح)\s+(?:ال)?جلسه$/.test(normalized) ||
    /^(?:تسجيل\s+الخروج|تسجيل\s+خروج|logout|log\s+out|لوج\s+اوت)$/.test(normalized)
  );
}

function getAdminStockUnlimitedCommand(messageText) {
  const normalized = normalizeArabicAdminCommand(messageText);
  if (/^تم\s+فتح\s+الاستعلام\s+عن\s+الارصده\s+بالكامل\s+لرقمك$/.test(normalized)) {
    return true;
  }
  if (/^تم\s+(?:الغاء|إلغاء|اقفال|إقفال|قفل)\s+الاستعلام\s+عن\s+الارصده\s+بالكامل\s+لرقمك$/.test(normalized)) {
    return false;
  }
  return null;
}

async function notifyBackendCompanyLink(chatId, phoneId, companyName) {
  await axios.post(
    `${backendBaseUrl}/api/admin/company-link`,
    { phone: phoneId, chat_id: chatId, company_name: companyName },
    {
      headers: {
        "X-Bridge-Token": adminToken
      },
      timeout: 15000
    }
  );
}

async function notifyBackendCompanyUnlink(chatId, phoneId) {
  await axios.post(
    `${backendBaseUrl}/api/admin/company-unlink`,
    { phone: phoneId, chat_id: chatId },
    {
      headers: {
        "X-Bridge-Token": adminToken
      },
      timeout: 15000
    }
  );
}

async function notifyBackendStockUnlimited(chatId, phoneId, enabled) {
  await axios.post(
    `${backendBaseUrl}/api/admin/stock-unlimited`,
    { phone: phoneId, chat_id: chatId, enabled },
    {
      headers: {
        "X-Bridge-Token": adminToken
      },
      timeout: 15000
    }
  );
}

function clearSupportHandoffTimer(chatId) {
  const existingEntry = supportHandoffTimers.get(chatId);
  if (existingEntry?.timer) {
    clearTimeout(existingEntry.timer);
    supportHandoffTimers.delete(chatId);
  }
}

function clearSupportSurvey(chatId) {
  const existingEntry = supportSurveyTimers.get(chatId);
  if (existingEntry?.timer) {
    clearTimeout(existingEntry.timer);
  }
  supportSurveyTimers.delete(chatId);
  supportSurveyPending.delete(chatId);
}

function scheduleSupportSurvey(chatId) {
  const cleanChatId = String(chatId || "").trim();
  if (!cleanChatId) {
    return;
  }
  clearSupportSurvey(cleanChatId);
  const timer = setTimeout(async () => {
    supportSurveyTimers.delete(cleanChatId);
    try {
      await sendPlainReply(cleanChatId, CUSTOMER_SERVICE_SURVEY_MESSAGE);
      supportSurveyPending.set(cleanChatId, Date.now() + CUSTOMER_SERVICE_SURVEY_PENDING_MS);
      console.log(`[Support Survey] Sent to ${cleanChatId}`);
    } catch (error) {
      console.error("Failed to send support survey:", error.message);
    }
  }, CUSTOMER_SERVICE_SURVEY_MS);
  supportSurveyTimers.set(cleanChatId, { timer, expiresAt: Date.now() + CUSTOMER_SERVICE_SURVEY_MS });
}

function parseSupportSurveyRating(messageText) {
  const normalized = normalizeMessageText(messageText)
    .replace(/[٠۰]/g, "0")
    .replace(/[١۱]/g, "1")
    .replace(/[٢۲]/g, "2")
    .replace(/[٣۳]/g, "3")
    .replace(/[٤۴]/g, "4")
    .replace(/[٥۵]/g, "5");
  const match = normalized.match(/^([1-5])(?:\s|$|[.?!،,؛:])/);
  return match ? match[1] : "";
}

async function maybeHandleSupportSurveyReply(chatId, messageText) {
  const expiresAt = supportSurveyPending.get(chatId);
  if (!expiresAt) {
    return false;
  }
  if (expiresAt <= Date.now()) {
    supportSurveyPending.delete(chatId);
    return false;
  }
  const rating = parseSupportSurveyRating(messageText);
  if (!rating) {
    return false;
  }
  supportSurveyPending.delete(chatId);
  console.log(`[Support Survey] ${chatId} rated ${rating}`);
  await sendPlainReply(chatId, CUSTOMER_SERVICE_SURVEY_THANKS);
  return true;
}

function isSupportHandoffActive(chatId) {
  const entry = supportHandoffTimers.get(chatId);
  if (!entry) {
    return false;
  }
  if (entry.expiresAt <= Date.now()) {
    clearSupportHandoffTimer(chatId);
    return false;
  }
  return true;
}

async function completeSupportHandoff(chatId) {
  clearSupportHandoffTimer(chatId);
  resumeChat(chatId, chatId);
  try {
    await sendPlainReply(chatId, CUSTOMER_SERVICE_HANDOFF_END);
  } catch (error) {
    console.error("Failed to send support handoff end message:", error.message);
  }

  try {
    await notifyBackendSupportHandoff("/api/support/handoff/end", chatId);
  } catch (error) {
    const details = error.response && error.response.data ? JSON.stringify(error.response.data) : "";
    console.error("Failed to clear support handoff in backend:", error.message, details);
  }
  scheduleSupportSurvey(chatId);
}

async function activateSupportHandoff(chatId) {
  clearSupportHandoffTimer(chatId);
  clearSupportSurvey(chatId);
  clearAndroidAppReminder(chatId);
  const expiresAt = Date.now() + CUSTOMER_SERVICE_HANDOFF_MS;
  const timer = setTimeout(() => {
    completeSupportHandoff(chatId).catch((error) => {
      console.error("Support handoff completion failed:", error.message);
    });
  }, CUSTOMER_SERVICE_HANDOFF_MS);
  supportHandoffTimers.set(chatId, { timer, expiresAt });
  
  await notifyBackendSupportHandoff("/api/support/handoff/start", chatId);
}

const STOCKFLOW_APP_SCREEN_CODES = new Set([
  "·",
  "··",
  "···",
  "····",
  "·····",
  "······",
  "·-·",
  "··-·",
  "-··",
  "·-··"
]);

function hasStockFlowAppScreenMarker(messageText) {
  const parts = String(messageText || "").trim().split(/\s+/).filter(Boolean);
  if (!parts.length) {
    return false;
  }
  const marker = parts[parts.length - 1].trim();
  return STOCKFLOW_APP_SCREEN_CODES.has(marker) || /^[·-]{1,10}$/.test(marker);
}

function cleanReminderName(value) {
  let cleaned = normalizeMessageText(value)
    .replace(/[\u200B-\u200F\u202A-\u202E]/g, "")
    .replace(/[~*_`|<>\[\]{}]/g, "")
    .trim();
  if (!cleaned || /^[-+()\d\s]+$/.test(cleaned)) {
    return "";
  }
  if (cleaned.length > 40) {
    cleaned = cleaned.slice(0, 40).trim();
  }
  return cleaned;
}

function pickAndroidReminderName(identity, senderName) {
  const cleanIdentity = identity && typeof identity === "object" ? identity : {};
  return (
    cleanReminderName(cleanIdentity.username) ||
    cleanReminderName(cleanIdentity.company_name) ||
    cleanReminderName(cleanIdentity.sender_name) ||
    cleanReminderName(senderName)
  );
}

function buildAndroidAppReminderMessage(identity, senderName) {
  const name = pickAndroidReminderName(identity, senderName);
  const namePart = name ? ` يا ${name}` : "";
  return [
    `أنا لاحظت${namePart} إن حضرتك مش بتستخدم التطبيق لسه 🙂`,
    "",
    "دلوقتي تقدر تحمل التطبيق من جوجل بلاي بسهولة:",
    STOCKFLOW_PLAY_STORE_URL,
    "",
    "عشان توصل أسرع 🚀"
  ].join("\n");
}

function normalizeClientContext(context) {
  const cleanContext = context && typeof context === "object" ? context : {};
  const type = normalizeMessageText(cleanContext.type || "").toLowerCase();
  const os = normalizeMessageText(cleanContext.os || "").toLowerCase();
  const browser = normalizeMessageText(cleanContext.browser || "").toLowerCase();
  const displayMode = normalizeMessageText(cleanContext.display_mode || "").toLowerCase();
  const standaloneValue = normalizeMessageText(cleanContext.is_standalone || "").toLowerCase();
  const isStandalone =
    cleanContext.is_standalone === true ||
    ["1", "true", "yes", "standalone"].includes(standaloneValue);
  const seenAtMs = Date.parse(String(cleanContext.seen_at || ""));
  const isFresh =
    !Number.isFinite(seenAtMs) ||
    Date.now() - seenAtMs <= ANDROID_APP_REMINDER_CONTEXT_MAX_AGE_MS;
  return { type, os, browser, displayMode, isStandalone, isFresh };
}

function isAndroidAppClientContext(context) {
  return (
    context.type === "android_app" ||
    context.type === "app" ||
    context.type.includes("mobile_app") ||
    (
      (context.os.includes("android") || context.type.includes("android")) &&
      (
        context.isStandalone ||
        ["standalone", "fullscreen", "minimal-ui"].includes(context.displayMode) ||
        context.type.includes("app")
      )
    )
  );
}

function isAndroidBrowserClientContext(context) {
  if (!context.isFresh || isAndroidAppClientContext(context)) {
    return false;
  }
  if (context.type === "android_browser") {
    return true;
  }
  const isAndroid = context.os.includes("android") || context.type.includes("android");
  const isBrowser =
    context.type === "browser" ||
    context.type.includes("browser") ||
    Boolean(context.browser);
  return isAndroid && isBrowser;
}

function clearAndroidAppReminder(chatId) {
  const cleanChatId = String(chatId || "").trim();
  if (!cleanChatId) {
    return;
  }
  const existingEntry = androidAppReminderTimers.get(cleanChatId);
  if (existingEntry?.timer) {
    clearTimeout(existingEntry.timer);
  }
  androidAppReminderTimers.delete(cleanChatId);
}

function recentlySentAndroidAppReminder(chatId) {
  const lastSentAt = androidAppReminderLastSent.get(String(chatId || "").trim()) || 0;
  return (
    Number.isFinite(lastSentAt) &&
    lastSentAt > 0 &&
    Date.now() - lastSentAt < ANDROID_APP_REMINDER_COOLDOWN_MS
  );
}

function scheduleAndroidAppReminder(chatId, phoneId, identity, senderName, reason) {
  const cleanChatId = String(chatId || "").trim();
  if (!cleanChatId || recentlySentAndroidAppReminder(cleanChatId)) {
    return;
  }
  clearAndroidAppReminder(cleanChatId);

  const delayMs =
    Number.isFinite(ANDROID_APP_REMINDER_MS) && ANDROID_APP_REMINDER_MS > 0
      ? ANDROID_APP_REMINDER_MS
      : 15 * 60 * 1000;
  const timer = setTimeout(async () => {
    androidAppReminderTimers.delete(cleanChatId);
    if (isSupportHandoffActive(cleanChatId) || isChatPaused(cleanChatId, phoneId)) {
      return;
    }
    try {
      await sendPlainReply(cleanChatId, buildAndroidAppReminderMessage(identity, senderName));
      androidAppReminderLastSent.set(cleanChatId, Date.now());
      saveAndroidAppReminderState();
      console.log(`[Android App Reminder] Sent to ${cleanChatId} (${reason})`);
    } catch (error) {
      console.error("Failed to send Android app reminder:", error.message);
    }
  }, delayMs);

  androidAppReminderTimers.set(cleanChatId, {
    timer,
    expiresAt: Date.now() + delayMs,
    reason: reason || "unknown"
  });
}

function maybeScheduleAndroidAppReminder({ chatId, phoneId, message, messageText, senderName, backendData }) {
  if (hasStockFlowAppScreenMarker(messageText)) {
    clearAndroidAppReminder(chatId);
    return;
  }

  const context = normalizeClientContext(backendData?.client_context || {});
  if (context.isFresh && isAndroidAppClientContext(context)) {
    clearAndroidAppReminder(chatId);
    return;
  }

  const identity = backendData?.identity || {};
  if (isAndroidBrowserClientContext(context)) {
    scheduleAndroidAppReminder(chatId, phoneId, identity, senderName, "site_android_browser");
  }
}

function clearReadyRecoveryTimer() {
  if (readyRecoveryTimer) {
    clearInterval(readyRecoveryTimer);
    readyRecoveryTimer = null;
  }
}

function startReadyRecoveryProbe() {
  clearReadyRecoveryTimer();
  let attempts = 0;
  readyRecoveryTimer = setInterval(async () => {
    attempts += 1;
    try {
      if (!client.pupPage || client.pupPage.isClosed()) {
        return;
      }

      const probe = await client.pupPage.evaluate(async () => {
        const socket = window.require?.("WAWebSocketModel")?.Socket;
        const hasSynced = Boolean(socket?.hasSynced);
        const state = socket?.state || "";
        const hasSyncHandler = typeof window.onAppStateHasSyncedEvent === "function";
        if (hasSynced && hasSyncHandler) {
          await window.onAppStateHasSyncedEvent();
          return { forced: true, hasSynced, state };
        }
        return { forced: false, hasSynced, state };
      });

      if (probe?.forced || bridgeState.status === "ready") {
        clearReadyRecoveryTimer();
        return;
      }
    } catch (error) {
      console.error("Ready recovery probe failed:", error.message);
    }

    if (attempts >= 24) {
      clearReadyRecoveryTimer();
    }
  }, 5000);
}

async function sendPlainReply(to, text, sourceMessage = null, phoneId = "") {
  const body = (text || "").trim();
  if (!body) {
    return;
  }
  stopTypingKeepAlive(to);

  // 1. Mark presence & seen
  await markChatSeenAndPresent(to, sourceMessage);

  // 2. Reading pause (human looks at chat before replying)
  const readingPauseMs = TYPING_ENABLED ? computeReadingDelayMs(body) : 0;
  if (readingPauseMs > 0) {
    await sleep(readingPauseMs);
  }

  // 3. Start typing indicator
  const typingDelayMs = TYPING_ENABLED ? computeTypingDelayMs(body) : 0;
  // Prefer the inbound Chat object so typing works for @lid conversations too.
  const typingChat = await startTypingIndicator(to, sourceMessage);
  try {
    if (typingDelayMs > 0) {
      await sleep(typingDelayMs);
    }
    rememberBotOutgoingFingerprint(to, body);
    const sentMessage = await withTimeout(
      client.sendMessage(to, body),
      SEND_MESSAGE_TIMEOUT_MS,
      "send_message"
    );
    rememberBotSentMessage(to, body, sentMessage);
    return sentMessage;
  } finally {
    // Always stop typing — even if sendMessage times out or throws.
    await stopTypingIndicator(typingChat, to, sourceMessage).catch(() => {});
  }
}

async function sendImmediateReply(to, text) {
  const body = (text || "").trim();
  if (!body) {
    return;
  }
  rememberBotOutgoingFingerprint(to, body);
  const sentMessage = await withTimeout(
    client.sendMessage(to, body),
    SEND_MESSAGE_TIMEOUT_MS,
    "send_message"
  );
  rememberBotSentMessage(to, body, sentMessage);
}

async function sendButtonsReply(to, body, buttons, title = "TOBY", footer = "") {
  const messageBody = String(body || "").trim();
  const buttonItems = (Array.isArray(buttons) ? buttons : [])
    .map((button) => ({
      id: String(button?.id || button?.body || "").trim(),
      body: String(button?.body || "").trim()
    }))
    .filter((button) => button.body)
    .slice(0, 3);

  if (!messageBody || !buttonItems.length) {
    throw new Error("Missing button message body or buttons");
  }

  const buttonMessage = new Buttons(messageBody, buttonItems, title, footer);
  const sentMessage = await client.sendMessage(to, buttonMessage);
  rememberBotSentMessage(to, messageBody, sentMessage);
  return sentMessage;
}

function getProvidedAdminToken(req) {
  const authHeader = (req.headers.authorization || "").trim();
  if (authHeader.startsWith("Bearer ")) {
    return authHeader.slice("Bearer ".length).trim();
  }
  return String(req.query.token || "").trim();
}

function requireAdmin(req, res, next) {
  if (!adminToken) {
    return res.status(503).json({ ok: false, message: "Bridge admin token is not configured." });
  }
  if (getProvidedAdminToken(req) !== adminToken) {
    return res.status(401).json({ ok: false, message: "Unauthorized" });
  }
  next();
}

async function pushState(extra = {}) {
  bridgeState = { ...bridgeState, ...extra };
  try {
    await axios.post(
      `${backendBaseUrl}/api/bridge/state`,
      bridgeState,
      {
        headers: {
          Authorization: `Bearer ${adminToken}`
        },
        timeout: 5000
      }
    );
  } catch (error) {
    console.error("Failed to push state:", error.message);
  }
}

const client = new Client({
  authStrategy: new LocalAuth({ clientId: "stockflow-toby" }),
  authTimeoutMs: 120000,
  qrMaxRetries: 0,
  takeoverOnConflict: true,
  puppeteer: {
    headless: "new",
    executablePath,
    dumpio: false,
    timeout: 120000,
    protocolTimeout: 180000,
    args: [
      "--no-sandbox",
      "--disable-setuid-sandbox",
      "--disable-dev-shm-usage",
      "--disable-gpu",
      "--disable-software-rasterizer",
      "--no-first-run",
      "--no-default-browser-check",
      "--disable-extensions",
      "--disable-background-networking",
      "--disable-default-apps",
      "--disable-sync",
      "--mute-audio",
      "--disable-notifications",
      "--disable-blink-features=AutomationControlled",
      "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ]
  }
});

async function initializeClient(reason = "WhatsApp client initialize requested") {
  if (initializeInFlight) {
    return false;
  }
  initializeInFlight = true;
  latestQr = null;
  await pushState({
    status: "initializing",
    qr_available: false,
    last_event: reason
  });
  try {
    await client.initialize();
    return true;
  } finally {
    initializeInFlight = false;
  }
}

async function restartClient(reason = "WhatsApp client restart requested") {
  clearReadyRecoveryTimer();
  try {
    await client.destroy();
  } catch (_error) {
  }
  return initializeClient(reason);
}

client.on("qr", async (qr) => {
  if (initializeRetryTimer) {
    clearTimeout(initializeRetryTimer);
    initializeRetryTimer = null;
  }
  latestQr = qr;
  await pushState({
    status: "waiting_for_qr_scan",
    qr_available: true,
    last_event: "QR updated"
  });
});

client.on("ready", async () => {
  clearReadyRecoveryTimer();
  clearInitializeRetry();
  latestQr = null;
  await pushState({
    status: "ready",
    qr_available: false,
    last_event: "WhatsApp connected"
  });
});

client.on("authenticated", async () => {
  await pushState({
    status: "authenticated",
    qr_available: false,
    last_event: "Session authenticated"
  });
  startReadyRecoveryProbe();
});

client.on("auth_failure", async (message) => {
  clearReadyRecoveryTimer();
  await pushState({
    status: "auth_failure",
    qr_available: false,
    last_event: `Authentication failed: ${message || "unknown"}`
  });
});

client.on("disconnected", async (reason) => {
  clearReadyRecoveryTimer();
  await pushState({
    status: "disconnected",
    qr_available: false,
    last_event: `Disconnected: ${reason || "unknown"}`
  });
});

client.on("call", async (call) => {
  const caller = String(call?.from || "").trim() || "unknown";
  const callType = call?.isVideo ? "video" : "voice";
  if (call?.fromMe) {
    console.log(`[toby call] Ignoring outgoing ${callType} call to ${caller}`);
    return;
  }
  if (!rememberAutoRejectedCall(call)) {
    console.log(`[toby call] Duplicate incoming ${callType} call ignored from ${caller}`);
    return;
  }

  try {
    await call.reject();
    console.log(`[toby call] Auto-rejected incoming ${callType} call from ${caller}`);
  } catch (error) {
    console.error(`Failed to auto-reject incoming ${callType} call from ${caller}:`, error.message);
    pushState({
      last_event: `Failed to auto-reject incoming ${callType} call from ${caller}: ${error.message}`
    }).catch((pushError) => {
      console.error("Failed to push call reject failure state:", pushError.message);
    });
    return;
  }

  try {
    await sendImmediateReply(caller, CALL_REJECT_REPLY);
    console.log(`[toby call] Sent call fallback reply to ${caller}`);
    pushState({
      last_event: `Auto-rejected incoming ${callType} call from ${caller} and sent fallback reply`
    }).catch((error) => {
      console.error("Failed to push call reject state:", error.message);
    });
  } catch (error) {
    console.error(`Failed to send call fallback reply to ${caller}:`, error.message);
    pushState({
      last_event: `Auto-rejected incoming ${callType} call from ${caller}, but failed to send fallback reply: ${error.message}`
    }).catch((pushError) => {
      console.error("Failed to push call reply failure state:", pushError.message);
    });
  }
});

async function handleInboundUserMessage(message) {
  let activeChatId = "";
  let dedupeToken = null;
  let phoneId = "";
  try {
    if (message.fromMe) {
      return;
    }
    dedupeToken = consumeInboundDedupe(message);
    if (!dedupeToken) {
      return;
    }
    if (isStatusBroadcastMessage(message)) {
      return;
    }
    const chatId = getMessageChatId(message);
    activeChatId = chatId;
    if (!chatId || chatId.includes("@g.us") || chatId.includes("@newsletter")) {
      return;
    }
    phoneId = await resolvePhoneForBackend(message, chatId);
    if (isChatPaused(chatId, phoneId)) {
      clearAndroidAppReminder(chatId);
      console.log("[toby inbound] Chat is paused:", chatId);
      return;
    }
    if (isSupportHandoffActive(chatId)) {
      clearAndroidAppReminder(chatId);
      return;
    }
    if (!acquireProcessingLock(chatId)) {
      console.log("[toby inbound] Ignoring overlapping message for", chatId);
      return;
    }

    console.log("[toby inbound]", chatId, message.type || "unknown");

    // ✅ اسم المرسل
    const senderName = String(
      (message._data && (message._data.notifyName || message._data.pushname)) || ""
    ).trim();

    // الرد على نفس chatId من واتساب (يبقى سليمًا مع @lid)
    const replyTarget = chatId;

    if (isUnsupportedMediaMessage(message)) {
      clearAndroidAppReminder(chatId);
      await sendPlainReply(replyTarget, UNSUPPORTED_MEDIA_REPLY, message, phoneId);
      return;
    }

    const isImageMessage = isImageLikeMediaMessage(message);
    // كذلك الـ document اللي mimetype بتاعته image/* نعامله كصورة (إيصالات بتيجي كـ Document)
    const isImageDocument = String(message?.type || "").toLowerCase() === "document" &&
      String(message?.mimetype || "").toLowerCase().startsWith("image/");
    // Image documents use the same retry/LID-aware path as regular images.
    // Keep the legacy branch unreachable for image documents so it cannot
    // bypass the stronger downloader below.
    if (isImageDocument && !isImageMessage) {
      clearAndroidAppReminder(chatId);
      try {
        await sendImmediateReply(
          replyTarget,
          "استلمت الملف ✅\nجاري مراجعته دلوقتي، وهبعتلك النتيجة بعد لحظات."
        );
        startTypingKeepAlive(replyTarget, message).catch((error) => {
          console.warn("Failed to start document typing state:", error.message);
        });
        let docMedia = null;
        try {
          docMedia = await message.downloadMedia();
        } catch (e) {
          console.warn(`[document] downloadMedia failed for ${chatId}:`, String(e.message || e).slice(0, 160));
        }
        if (docMedia && docMedia.data) {
          console.log(`[document] Downloaded image document for ${chatId}, sending to backend`);
          const docPayload = {
            phone: phoneId,
            chat_id: chatId,
            message: (message.body || message.caption || "[ملف]").trim() || "[ملف]",
            sender_name: senderName,
            image_base64: docMedia.data,
            image_mimetype: docMedia.mimetype || "image/jpeg",
            image_download_failed: false
          };
          const docResponse = await axios.post(
            `${backendBaseUrl}/api/chat/reply`,
            docPayload,
            { headers: { "X-Bridge-Token": adminToken }, timeout: IMAGE_REPLY_TIMEOUT_MS }
          );
          const docReply = docResponse.data && docResponse.data.reply;
          if (docReply && String(docReply).trim()) {
            await sendPlainReply(replyTarget, docReply, message, phoneId);
          }
        } else {
          await sendPlainReply(
            replyTarget,
            "وصلتني الملف بس معرفتش أفتحه 😔\nجرب تبعت الصورة مباشرة من الجاليري (مش كملف).",
            message,
            phoneId
          );
        }
        return;
      } catch (docErr) {
        console.error("Failed to process document image:", docErr.message);
        await sendPlainReply(replyTarget, "حصلت مشكلة في معالجة الملف. جرب تبعت الصورة عادي من الجاليري.", message, phoneId);
        return;
      }
    }
    if (isImageMessage) {
      clearAndroidAppReminder(chatId);
      try {
        await sendImmediateReply(
          replyTarget,
          "استلمت الصورة ✅\nجاري مراجعتها دلوقتي، وهبعتلك النتيجة بعد لحظات."
        );
        startTypingKeepAlive(replyTarget, message).catch((error) => {
          console.warn("Failed to start image typing state:", error.message);
        });
        // WhatsApp Web occasionally gives us a detached message object (most
        // often for @lid chats).  For @lid chats, the media metadata is often
        // not synced to the web client — we need to resolve the LID to a
        // phone number and look the message up in the phone-based chat.
        let media = null;
        let mediaMessage = message;
        let resolvedAlternateChatId = "";
        const isLidChat = String(chatId || "").endsWith("@lid");
        const lidAlternateChatIds = [];
        const rememberLidAlternate = (candidate) => {
          const clean = String(candidate || "").trim();
          if (!clean || lidAlternateChatIds.includes(clean)) {
            return;
          }
          lidAlternateChatIds.push(clean);
        };
        if (isLidChat) {
          // phoneId was already resolved above via resolvePhoneForBackend (cache/contact/LID API).
          // resolvePhoneFromContact often times out on the second call — reuse the good phoneId
          // so downloadMediaDirect searches the @c.us chat where media metadata actually lives.
          if (phoneId && phoneId.endsWith("@c.us") && isValidLidPhoneMapping(chatId, phoneId)) {
            rememberLidAlternate(phoneId);
          }
          // Refresh phone resolution from the live contact before media lookup.
          const refreshedPhone = await resolvePhoneFromContact(message, chatId);
          if (refreshedPhone && isValidLidPhoneMapping(chatId, refreshedPhone)) {
            phoneId = refreshedPhone;
            rememberLidAlternate(refreshedPhone);
          }
          // @lid store rarely has downloadable media — keep as last-resort only.
          rememberLidAlternate(chatId);
        }
        // Media metadata for @lid messages may arrive late. Keep the request
        // in the background (typing indicator stays alive) instead of sending
        // a false "download failed" event to the backend after five seconds.
        const maxAttempts = isLidChat ? 8 : 6;
        const retryWaitsMs = isLidChat
          ? [3000, 6000, 10000, 15000, 20000, 30000, 30000]
          : [2500, 4000, 7000, 12000, 20000];
        const eagerMedia = await (() => {
          const msgId = message.id?._serialized;
          if (msgId && !eagerImageDownloads.has(msgId)) {
            startEagerImageDownload(message);
          }
          return consumeEagerImageDownload(msgId, EAGER_IMAGE_DOWNLOAD_MS);
        })();
        if (eagerMedia?.data) {
          media = eagerMedia;
          console.log(`[image] Used eager download cache for ${chatId}`);
        }
        for (let attempt = 1; attempt <= maxAttempts; attempt++) {
          if (media?.data) {
            break;
          }
          try {
            if (attempt > 1 && typeof client.getMessageById === "function") {
              const freshMessage = await client.getMessageById(message.id._serialized);
              if (freshMessage) {
                mediaMessage = freshMessage;
              }
            }
            if (typeof mediaMessage.reload === "function") {
              try {
                await mediaMessage.reload();
              } catch (reloadError) {
                console.warn(
                  `[image] message reload attempt ${attempt}/${maxAttempts} failed for ${chatId}:`,
                  String(reloadError && reloadError.message ? reloadError.message : reloadError).slice(0, 160)
                );
              }
            }
            media = await mediaMessage.downloadMedia({
              downloadEvenIfExpensive: true,
              rmrReason: 1,
            });
            if (media && media.data) {
              break;
            }
          } catch (downloadError) {
            console.warn(
              `[image] downloadMedia attempt ${attempt}/${maxAttempts} failed for ${chatId}:`,
              String(downloadError && downloadError.message ? downloadError.message : downloadError).slice(0, 160)
            );
          }
          // For @lid chats, try resolving the LID to a phone-based chat ID
          // and download directly from the underlying WhatsApp store.
          if (isLidChat && !media) {
            if (!resolvedAlternateChatId) {
              try {
                resolvedAlternateChatId = await resolveLidToPhoneChatId(client, chatId);
                if (resolvedAlternateChatId) {
                  phoneId = resolvedAlternateChatId;
                  console.log(
                    `[image] LID ${chatId} resolved to phone chat ${resolvedAlternateChatId} for media download`
                  );
                }
              } catch (lidErr) {
                console.warn(`[image] LID resolution failed for ${chatId}:`, String(lidErr.message || lidErr).slice(0, 160));
              }
            }
            if (resolvedAlternateChatId) {
              rememberLidAlternate(resolvedAlternateChatId);
            }
            for (const alternateChatId of lidAlternateChatIds.slice().sort((a, b) => {
              const aIsPhone = String(a).endsWith("@c.us") ? 0 : 1;
              const bIsPhone = String(b).endsWith("@c.us") ? 0 : 1;
              return aIsPhone - bIsPhone;
            })) {
              if (media && media.data) {
                break;
              }
              try {
                const directMedia = await downloadMediaDirect(
                  client,
                  message.id._serialized,
                  alternateChatId,
                  message.timestamp
                );
                if (directMedia && directMedia.data) {
                  media = directMedia;
                  resolvedAlternateChatId = alternateChatId;
                  console.log(
                    `[image] Direct store download succeeded for ${chatId} via ${alternateChatId}`
                  );
                  break;
                }
                console.warn(
                  `[image] Direct store download returned no media for ${chatId} via ${alternateChatId}`
                );
              } catch (directErr) {
                console.warn(
                  `[image] Direct store download attempt ${attempt} via ${alternateChatId} failed:`,
                  String(directErr.message || directErr).slice(0, 160)
                );
              }
            }
          }
          // NUCLEAR FALLBACK for @lid chats: query the WhatsApp internal store
          // directly via page.evaluate — getChatById rejects for @lid resolved
          // chats with the minified rejection "r". Using WAWebCollections.Chat
          // bypasses the wrapper entirely.
          if (isLidChat && !media && attempt >= 2 && client && client.pupPage) {
            const fallbackAlternateIds = lidAlternateChatIds.length
              ? lidAlternateChatIds
              : [resolvedAlternateChatId || chatId];
            for (const alternateChatId of fallbackAlternateIds.slice().sort((a, b) => {
              const aIsPhone = String(a).endsWith("@c.us") ? 0 : 1;
              const bIsPhone = String(b).endsWith("@c.us") ? 0 : 1;
              return aIsPhone - bIsPhone;
            })) {
              if (!alternateChatId || (media && media.data)) {
                continue;
              }
              try {
                const targetTs = Number(message.timestamp || 0);
                const fallbackResult = await client.pupPage.evaluate(async function(altId, hintTs) {
                function sleep(ms) { return new Promise(function(r) { setTimeout(r, ms); }); }
                function getField(m, k) {
                  if (!m) return undefined;
                  if (m[k] !== undefined && m[k] !== null) return m[k];
                  if (m.mediaData && m.mediaData[k] !== undefined && m.mediaData[k] !== null) return m.mediaData[k];
                  return undefined;
                }
                try {
                  var Chat = window.require('WAWebCollections').Chat;
                  var chat = Chat.get(altId);
                  if (!chat) return { error: 'chat_not_in_store' };
                  var allMsgs = chat.getMessages
                    ? await chat.getMessages({ count: 200 })
                    : (chat.msgs && Array.from(chat.msgs.models || []));
                  var list = Array.isArray(allMsgs) ? allMsgs : [];
                  var imageMsg = list
                    .filter(function(m) {
                      var t = String((m && m.type) || '').toLowerCase();
                      var mime = String(getField(m, 'mimetype') || (m && m.mimetype) || '').toLowerCase();
                      return t === 'image' || (t === 'document' && mime.startsWith('image/'));
                    })
                    .filter(function(m) {
                      if (!hintTs) return true;
                      var ts = (m && (m.t || m.timestamp)) || 0;
                      return Math.abs(ts - hintTs) <= 180;
                    })
                    .sort(function(a, b) {
                      var bk = Number(!!(getField(b, 'directPath') && getField(b, 'mediaKey')));
                      var ak = Number(!!(getField(a, 'directPath') && getField(a, 'mediaKey')));
                      if (bk !== ak) return bk - ak;
                      return Math.abs(((a && (a.t||a.timestamp))||0) - hintTs) - Math.abs(((b && (b.t||b.timestamp))||0) - hintTs);
                    })[0];
                  if (!imageMsg) return { error: 'no_image_in_window', count: list.length };
                  var dp = getField(imageMsg, 'directPath');
                  var mk = getField(imageMsg, 'mediaKey');
                  if (!dp || !mk) {
                    try { await imageMsg.downloadMedia({ downloadEvenIfExpensive: true, rmrReason: 1 }); } catch(e) {}
                    await sleep(2000);
                    dp = getField(imageMsg, 'directPath');
                    mk = getField(imageMsg, 'mediaKey');
                  }
                  if (dp && mk) {
                    var mockQpl = { addAnnotations: function() { return this; }, addPoint: function() { return this; } };
                    var decrypted = await window.require('WAWebDownloadManager').downloadManager.downloadAndMaybeDecrypt({
                      directPath: dp,
                      encFilehash: getField(imageMsg, 'encFilehash'),
                      filehash: getField(imageMsg, 'filehash'),
                      mediaKey: mk,
                      mediaKeyTimestamp: getField(imageMsg, 'mediaKeyTimestamp'),
                      type: getField(imageMsg, 'type') || 'image',
                      signal: new AbortController().signal,
                      downloadQpl: mockQpl,
                    });
                    var data = await window.WWebJS.arrayBufferToBase64Async(decrypted);
                    return { data: data, mimetype: getField(imageMsg, 'mimetype') || 'image/jpeg' };
                  }
                  // DOM Fallback
                  var domImgs = Array.from(document.querySelectorAll('img[src^="blob:"], img[src^="data:image"]'));
                  if (domImgs.length > 0) {
                    var last = domImgs[domImgs.length - 1];
                    if (last.src.startsWith('data:image')) {
                      return { data: last.src.split(',')[1], mimetype: 'image/jpeg' };
                    }
                    var r = await fetch(last.src);
                    var b = await r.blob();
                    var rd = new FileReader();
                    var b64Data = await new Promise(function(res) {
                      rd.onloadend = function() {
                        var str = String(rd.result || '');
                        res(str.includes(',') ? str.split(',')[1] : str);
                      };
                      rd.readAsDataURL(b);
                    });
                    if (b64Data && b64Data.length > 200) {
                      return { data: b64Data, mimetype: b.type || 'image/jpeg' };
                    }
                  }
                  return { error: 'missing_keys_after_retry' };
                } catch(e) {
                  return { error: 'store_fallback_exception:' + (e && e.message ? e.message : String(e)) };
                }
              }, alternateChatId, targetTs);
                if (fallbackResult && fallbackResult.data) {
                  media = { data: fallbackResult.data, mimetype: fallbackResult.mimetype || 'image/jpeg' };
                  resolvedAlternateChatId = alternateChatId;
                  console.log('[image] @lid store-fallback succeeded for ' + chatId + ' via ' + alternateChatId);
                  break;
                }
                console.warn(
                  '[image] @lid store-fallback failed for ' + chatId + ' via ' + alternateChatId + ':',
                  fallbackResult ? fallbackResult.error : 'no_result'
                );
              } catch (fbErr) {
                console.warn(
                  '[image] @lid store-fallback exception for ' + chatId + ' via ' + alternateChatId + ':',
                  String(fbErr.message || fbErr).slice(0, 200)
                );
              }
            }
          }
          if (attempt < maxAttempts) {
            await new Promise((resolve) => setTimeout(resolve, retryWaitsMs[attempt - 1] || 5000));
          }
        }
        if (!media || !media.data) {
          console.warn(
            `[image] All ${maxAttempts} media attempts failed for ${chatId}; ` +
            "forwarding image_download_failed=true to backend so Toby can reply."
          );
          // Stop the keepalive interval but let the backend generate the reply.
          // Using sendImmediateReply (no typing delay) here avoids the risk of
          // a stuck typing indicator if sendMessage itself hangs.
          stopTypingKeepAlive(replyTarget);
          try {
            const failPayload = {
              phone: phoneId,
              chat_id: chatId,
              message: (message.body || message.caption || "[صورة]").trim() || "[صورة]",
              sender_name: senderName,
              image_base64: null,
              image_mimetype: "image/jpeg",
              image_download_failed: true,
            };
            const failResponse = await axios.post(
              `${backendBaseUrl}/api/chat/reply`,
              failPayload,
              { headers: { "X-Bridge-Token": adminToken }, timeout: IMAGE_REPLY_TIMEOUT_MS }
            );
            const failReply = failResponse.data && failResponse.data.reply;
            if (failReply && String(failReply).trim()) {
              await sendImmediateReply(replyTarget, String(failReply).trim());
            }
          } catch (backendErr) {
            console.warn("[image] backend call for image_download_failed also failed:", String(backendErr.message || backendErr).slice(0, 160));
            // Last-resort fallback — send a plain message without typing delay.
            await sendImmediateReply(
              replyTarget,
              "لسه الصورة ماوصلتش كاملة من واتساب 😔\nابعتها تاني كصورة مباشرة من الجاليري."
            );
          }
          return;
        }

        const imagePayload = {
          phone: phoneId,
          chat_id: chatId,
          message: (message.body || message.caption || "[صورة]").trim() || "[صورة]",
          sender_name: senderName,
          image_base64: media ? media.data : null,
          image_mimetype: media ? media.mimetype : "image/jpeg",
          image_download_failed: !media || !media.data
        };
        const imgResponse = await axios.post(
          `${backendBaseUrl}/api/chat/reply`,
          imagePayload,
          { headers: { "X-Bridge-Token": adminToken }, timeout: IMAGE_REPLY_TIMEOUT_MS }
        );
        const imgReply = imgResponse.data && imgResponse.data.reply;
        if (imgReply && String(imgReply).trim()) {
          await sendPlainReply(replyTarget, imgReply, message, phoneId);
        } else if (imgResponse?.data?.ok && !imgReply) {
          console.warn("[toby inbound] Empty image reply body for", replyTarget);
        }
        return;
      } catch (imgErr) {
        console.error("Failed to process image message:", imgErr.message);
        await sendPlainReply(replyTarget, "حصلت مشكلة في معالجة الصورة. جرب تبعتها تاني.", message, phoneId);
        return;
      }
    }

    const messageText = (message.body || "").trim();
    if (!messageText) {
      return;
    }
    clearAndroidAppReminder(chatId);
    if (await maybeHandleSupportSurveyReply(chatId, messageText)) {
      return;
    }
    startTypingKeepAlive(replyTarget, message).catch((error) => {
      console.warn("Failed to start inbound typing state:", error.message);
    });

    const payload = {
      phone: phoneId,
      chat_id: chatId,
      message: messageText,
      sender_name: senderName
    };

    const response = await axios.post(
      `${backendBaseUrl}/api/chat/reply`,
      payload,
      {
        headers: {
          "X-Bridge-Token": adminToken
        },
        timeout: 15000
      }
    );

    const responseData = response.data || {};
    const reply = responseData.reply;
    if (reply && String(reply).trim()) {
      await sendPlainReply(replyTarget, reply, message, phoneId);
      console.log("[toby inbound] Sent reply to", replyTarget);
    } else if (response?.data?.ok === true && !reply) {
      console.warn("[toby inbound] Empty reply from backend for", replyTarget);
    }
    maybeScheduleAndroidAppReminder({
      chatId,
      phoneId,
      message,
      messageText,
      senderName,
      backendData: responseData
    });
  } catch (error) {
    const details = error.response && error.response.data ? JSON.stringify(error.response.data) : "";
    console.error("Failed to process message:", error.message, details);
    try {
      const fallbackTo = getMessageChatId(message) || message.from;
      await sendPlainReply(fallbackTo, "حصلت مشكلة مؤقتة أثناء معالجة رسالتك. حاول مرة ثانية خلال لحظات.", message, phoneId);
    } catch (sendError) {
      console.error("Failed to send fallback reply:", sendError.message);
    }
  } finally {
    finalizeInboundDedupe(dedupeToken);
    if (activeChatId) {
      releaseProcessingLock(activeChatId);
    }
  }
}

client.on("message_create", (message) => {
  if (!message.fromMe && isImageLikeMediaMessage(message)) {
    startEagerImageDownload(message);
  }
});

client.on("message_create", (message) => {
  if (message.fromMe) {
    return;
  }
  lastInboundTime = Date.now(); // تحديث آخر وقت لرسالة inbound
  handleInboundUserMessage(message).catch((err) =>
    console.error("handleInboundUserMessage failed:", err.message)
  );
});

client.on("message_create", async (message) => {
  try {
    if (!message.fromMe) {
      return;
    }
    if (isStatusBroadcastMessage(message)) {
      return;
    }

    const chatId = getMessageChatId(message);
    if (!chatId || chatId.includes("@g.us") || chatId.includes("@newsletter")) {
      return;
    }
    if (isKnownBotSentMessage(message, chatId)) {
      return;
    }
    const phoneId = await resolvePhoneForBackend(message, chatId);

    const messageText = normalizeMessageText(message.body || "");
    const cleanMessageText = messageText.replace(/[.?!،]/g, "").trim();

    const adminCommandText = normalizeArabicAdminCommand(messageText).toLowerCase();
    // الأوامر لازم تتكتب ببادئة "/" عشان رد عادي من موظف الدعم (زي "شغل" أو
    // "رجع" أو "تفعيل") ما يشغّلش/يوقفش توبي بالغلط في نص محادثة حقيقية مع عميل.
    // ده كان السبب في أعطال فعلية سابقة (شات فضل "موقّف" لازم يتصحح يدوي).
    const isPauseCommand = /^\/(ايقاف|توقيف|وقف|بوز|باوز|pause)(\s+(توبي|toby))?$/i.test(adminCommandText);
    const isResumeCommand = /^\/(اعاده|تفعيل|تشغيل|شغل|رجع|استئناف|resume)(\s+(توبي|toby))?$/i.test(adminCommandText);

    if (isPauseCommand) {
      pauseChat(chatId, phoneId);
      console.log(`[Admin Command] Toby paused for ${chatId}`);
      return;
    }

    if (isResumeCommand) {
      resumeChat(chatId, phoneId);
      console.log(`[Admin Command] Toby resumed for ${chatId}`);
      return;
    }

    if (messageText === normalizeMessageText("حذف الجلسه") || messageText === normalizeMessageText("حذف الجلسة")) {
      try {
        await notifyBackendCompanyUnlink(chatId, phoneId);
        console.log(`[Admin Company Unlink] ${chatId}`);
      } catch (err) {
        console.error("Failed to unlink company identity:", err.message);
      }
      return;
    }

    const adminCompanyName = extractAdminCompanyLinkName(messageText);
    if (adminCompanyName) {
      await notifyBackendCompanyLink(chatId, phoneId, adminCompanyName);
      console.log(`[Admin Company Link] ${chatId} -> ${adminCompanyName}`);
      return;
    }

    if (isAdminCompanyUnlinkCommand(messageText)) {
      await notifyBackendCompanyUnlink(chatId, phoneId);
      console.log(`[Admin Company Unlink] ${chatId}`);
      return;
    }

    const stockUnlimitedEnabled = getAdminStockUnlimitedCommand(messageText);
    if (stockUnlimitedEnabled !== null) {
      await notifyBackendStockUnlimited(chatId, phoneId, stockUnlimitedEnabled);
      console.log(
        `[Admin Stock Unlimited] ${stockUnlimitedEnabled ? "enabled" : "disabled"} for ${chatId}`
      );
      return;
    }

    // أمر "فعل <رقم>" لتفعيل البلس يدويًا. لازم رقم واضح (8-15 رقم) بعد كلمة
    // "فعل" ومسافة مباشرة، عشان كلمة زي "فعلاً" أو "فعل ايه" في رد الموظف
    // الطبيعي للعميل ما تشغّلش الأمر ده بالغلط. وأي فشل يتسجل في اللوج بس،
    // وماترجعش رسالة خطأ خام لأي شات (كان ممكن يوصل للعميل نفسه بالغلط).
    const activateProMatch = (message.body || "").trim().match(/^فعل\s+(?:الرقم\s+)?(\d{8,15})\b/);
    if (activateProMatch) {
      let targetPhone = activateProMatch[1];
      if (message.hasQuotedMsg) {
        try {
          const quotedMsg = await message.getQuotedMessage();
          const quotedMatch = (quotedMsg.body || "").match(/الرقم:\s*(\d{8,15})/);
          if (quotedMatch) {
            targetPhone = quotedMatch[1];
          }
        } catch (err) {
          console.error("[Admin Command] Failed to read quoted message for activate-pro:", err.message);
        }
      }

      try {
        await axios.post(
          `${backendBaseUrl}/api/admin/activate-pro`,
          { phone: targetPhone },
          { headers: { "X-Bridge-Token": adminToken }, timeout: 15000 }
        );
        await sendPlainReply(chatId, `تم التفعيل بنجاح للرقم ${targetPhone} وإرسال الكود للعميل.`);
      } catch (err) {
        console.error(`[Admin Command] Failed to activate pro for ${targetPhone}:`, err.message);
      }
      return;
    }

    if (
      messageText === normalizeMessageText(CUSTOMER_SERVICE_HANDOFF_TRIGGER) ||
      messageText === normalizeMessageText(CUSTOMER_SERVICE_HANDOFF_TRIGGER_LEGACY) ||
      messageText === "."
    ) {
      await activateSupportHandoff(chatId);
      return;
    }

    if (messageText === normalizeMessageText(CUSTOMER_SERVICE_HANDOFF_END)) {
      clearSupportHandoffTimer(chatId);
      resumeChat(chatId, phoneId);
      try {
        await notifyBackendSupportHandoff("/api/support/handoff/end", chatId);
      } catch (error) {
        const details = error.response && error.response.data ? JSON.stringify(error.response.data) : "";
        console.error("Failed to clear manual support handoff in backend:", error.message, details);
      }
      scheduleSupportSurvey(chatId);
      return;
    }

    if (isSupportHandoffActive(chatId)) {
      return;
    }
  } catch (error) {
    const details = error.response && error.response.data ? JSON.stringify(error.response.data) : "";
    console.error("Failed to process admin outgoing message:", error.message, details);
  }
});

app.get("/health", (_req, res) => {
  res.json({ ok: true, bridgeState });
});

app.get("/status", requireAdmin, (_req, res) => {
  res.json({ ok: true, bridgeState, qr_available: Boolean(latestQr) });
});

app.get("/blocked-chats", requireAdmin, (_req, res) => {
  res.json({ ok: true, chat_ids: Array.from(pausedChatIds).sort() });
});

app.post("/block-chat", requireAdmin, (req, res) => {
  const chatId = normalizeManualChatId(req.body?.phone || req.body?.chat_id || req.body?.to);
  if (!chatId) {
    return res.status(400).json({ ok: false, message: "Missing phone or chat_id" });
  }
  pauseChat(chatId, chatId);
  res.json({ ok: true, chat_id: chatId, chat_ids: Array.from(pausedChatIds).sort() });
});

app.post("/unblock-chat", requireAdmin, (req, res) => {
  const chatId = normalizeManualChatId(req.body?.phone || req.body?.chat_id || req.body?.to);
  if (!chatId) {
    return res.status(400).json({ ok: false, message: "Missing phone or chat_id" });
  }
  resumeChat(chatId, chatId);
  res.json({ ok: true, chat_id: chatId, chat_ids: Array.from(pausedChatIds).sort() });
});

app.get("/qr.png", requireAdmin, async (_req, res) => {
  if (!latestQr) {
    return res.status(404).json({ ok: false, message: "QR is not available right now." });
  }
  try {
    const buffer = await QRCode.toBuffer(latestQr, { width: 520, margin: 6 });
    res.setHeader("Content-Type", "image/png");
    res.send(buffer);
  } catch (error) {
    res.status(500).json({ ok: false, message: error.message });
  }
});

app.get("/screenshot.png", requireAdmin, async (_req, res) => {
  if (!client?.pupPage) {
    return res.status(404).json({ ok: false, message: "Page is not initialized." });
  }
  try {
    const buffer = await client.pupPage.screenshot({ type: "png" });
    res.setHeader("Content-Type", "image/png");
    res.send(buffer);
  } catch (error) {
    res.status(500).json({ ok: false, message: error.message });
  }
});

// Restricted media diagnostics for WhatsApp @lid download issues. This only
// returns metadata/presence flags; it never returns image bytes or media keys.
app.get("/debug/media", requireAdmin, async (req, res) => {
  if (!client?.pupPage) {
    return res.status(404).json({ ok: false, message: "Page is not initialized." });
  }
  const chatId = String(req.query.chat_id || "").trim();
  const messageId = String(req.query.message_id || "").trim();
  const timestamp = Number(req.query.timestamp || 0);
  try {
    const result = await client.pupPage.evaluate(
      async ({ chatId, messageId, timestamp }) => {
        const Msg = window.require("WAWebCollections").Msg;
        const Chat = window.require("WAWebCollections").Chat;
        const summarize = (candidate) => {
          if (!candidate) return null;
          return {
            id: candidate.id?._serialized || "",
            remote: candidate.id?.remote || candidate.from || candidate.to || "",
            t: candidate.t || candidate.timestamp || 0,
            type: String(candidate.type || ""),
            mimetype: String(candidate.mimetype || ""),
            isMedia: Boolean(candidate.isMedia),
            hasMediaData: Boolean(candidate.mediaData),
            mediaStage: candidate.mediaData ? String(candidate.mediaData.mediaStage || "") : "",
            hasDirectPath: Boolean(candidate.directPath),
            hasMediaKey: Boolean(candidate.mediaKey),
            hasEncFilehash: Boolean(candidate.encFilehash),
            hasFilehash: Boolean(candidate.filehash),
          };
        };
        const isImage = (candidate) => {
          const type = String(candidate?.type || "").toLowerCase();
          const mimetype = String(candidate?.mimetype || "").toLowerCase();
          return type === "image" || (type === "document" && mimetype.startsWith("image/"));
        };
        const distance = (candidate) => Math.abs(Number(candidate?.t || candidate?.timestamp || 0) - timestamp);
        const exact = messageId
          ? (Msg.get(messageId) || (Msg.getMessagesById && (await Msg.getMessagesById([messageId]))?.messages?.[0]))
          : null;
        let chatMessages = [];
        if (chatId) {
          const chat = Chat.get(chatId) ||
            (window.WWebJS?.getChat
              ? await window.WWebJS.getChat(chatId, { getAsModel: false })
              : null);
          if (chat) {
            try {
              const messages = chat.getMessages
                ? await chat.getMessages({ count: 200 })
                : (chat.msgs && Array.from(chat.msgs.models || []));
              chatMessages = Array.isArray(messages) ? messages : [];
            } catch (_) {}
          }
        }
        const allModels = Array.from(Msg.models || Msg._models || []);
        const nearby = allModels
          .filter(isImage)
          .filter((candidate) => !timestamp || distance(candidate) <= 180)
          .sort((a, b) => distance(a) - distance(b))
          .slice(0, 12)
          .map(summarize);
        return {
          collectionSize: allModels.length,
          exact: summarize(exact),
          chatImages: chatMessages.filter(isImage).slice(-20).map(summarize),
          nearbyImages: nearby,
        };
      },
      { chatId, messageId, timestamp }
    );
    return res.json({ ok: true, result });
  } catch (error) {
    return res.status(500).json({ ok: false, message: error.message });
  }
});

app.post("/ensure-qr", requireAdmin, async (_req, res) => {
  if (latestQr) {
    return res.json({ ok: true, qr_available: true, bridgeState });
  }
  if (["ready", "authenticated"].includes(bridgeState.status)) {
    return res.json({
      ok: true,
      qr_available: false,
      already_connected: true,
      bridgeState
    });
  }

  restartClient("QR requested from desktop admin").catch(async (error) => {
    console.error("Failed to prepare QR:", error.message);
    await pushState({
      status: "qr_prepare_failed",
      qr_available: false,
      last_event: `Failed to prepare QR: ${error.message}`
    });
  });
  res.json({ ok: true, qr_available: false, preparing: true, bridgeState });
});

// ✅ endpoint لإرسال رسالة واتساب من الـ backend للإدارة
app.post("/api/send-admin", requireAdmin, async (req, res) => {
  try {
    const { to, message: msgText } = req.body || {};
    if (!to || !msgText) {
      return res.status(400).json({ ok: false, message: "Missing to or message" });
    }
    const jid = to.replace(/\D/g, "") + "@c.us";
    if (client && typeof client.isRegisteredUser === "function") {
      const isRegistered = await client.isRegisteredUser(jid).catch(() => true);
      if (!isRegistered) {
        console.warn(`[send-admin] Recipient ${jid} is not registered on WhatsApp.`);
        return res.status(400).json({ ok: false, message: "Recipient number is not registered on WhatsApp" });
      }
    }
    const sentMessage = await sendPlainReply(jid, String(msgText));
    res.json({
      ok: true,
      message_id: String(sentMessage?.id?._serialized || sentMessage?.id?.id || "") || undefined
    });
  } catch (error) {
    res.status(500).json({ ok: false, message: error.message });
  }
});

app.post("/api/send-buttons", requireAdmin, async (req, res) => {
  try {
    const { to, message: msgText, buttons, title, footer } = req.body || {};
    if (!to || !msgText || !Array.isArray(buttons) || !buttons.length) {
      return res.status(400).json({ ok: false, message: "Missing to, message, or buttons" });
    }
    const jid = to.replace(/\D/g, "") + "@c.us";
    const sentMessage = await sendButtonsReply(jid, String(msgText), buttons, title, footer);
    res.json({ ok: true, message_id: sentMessage?.id?._serialized || null });
  } catch (error) {
    res.status(500).json({ ok: false, message: error.message });
  }
});

app.post("/reconnect", requireAdmin, async (_req, res) => {
  try {
    await restartClient("Reconnect requested from admin");
    res.json({ ok: true });
  } catch (error) {
    res.status(500).json({ ok: false, message: error.message });
  }
});

app.post("/logout-reset", requireAdmin, async (_req, res) => {
  try {
    try {
      await client.logout();
    } catch (_error) {
    }
    await client.destroy();
    latestQr = null;
    await pushState({
      status: "resetting_session",
      qr_available: false,
      last_event: "WhatsApp session reset requested"
    });
    fs.rmSync(sessionDir, { recursive: true, force: true });
    setTimeout(() => {
      initializeClient("WhatsApp session reset; waiting for new QR").catch((error) => {
        console.error("Failed to initialize after logout reset:", error.message);
      });
    }, 1500);
    res.json({ ok: true });
  } catch (error) {
    res.status(500).json({ ok: false, message: error.message });
  }
});

app.listen(port, async () => {
  if (!adminToken) {
    console.error("Refusing to start TOBY bridge without an admin token.");
    process.exit(1);
  }
  loadPausedChats();
  loadPhoneCache();
  loadAndroidAppReminderState();
  console.log(`Toby bridge listening on ${port}`);
  await pushState({
    status: "starting",
    qr_available: false,
    last_event: "Bridge HTTP API started"
  });
  initializeClient("Bridge startup").catch((error) => {
    handleInitializationFailure(error).catch((stateError) => {
      console.error("Failed to record WhatsApp initialization failure:", stateError.message);
    });
  });
});
