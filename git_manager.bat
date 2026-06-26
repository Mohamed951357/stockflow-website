@echo off
chcp 65001 >nul
set GIT_DIR=d:\StockFlow_Collection\ملفات الموقع\.git
set GIT_WORK_TREE=d:\StockFlow_Collection\ملفات الموقع
cd /d "d:\StockFlow_Collection\ملفات الموقع"

:MENU
cls
echo.
echo  ╔══════════════════════════════════════════╗
echo  ║     StockFlow - Git Manager              ║
echo  ║     https://github.com/Mohamed951357/    ║
echo  ║     stockflow-website                    ║
echo  ╚══════════════════════════════════════════╝
echo.
echo  [1] حفظ التعديلات (commit)
echo  [2] رفع على GitHub (push)
echo  [3] حفظ ورفع معاً (الأكثر استخداماً)
echo  [4] عرض سجل التعديلات
echo  [5] الرجوع لنسخة قديمة - مشاهدة
echo  [6] استرجاع ملف معين من نسخة قديمة
echo  [7] الرجوع للنسخة الأحدث
echo  [0] خروج
echo.
set /p choice="اختر رقم: "

if "%choice%"=="1" goto COMMIT
if "%choice%"=="2" goto PUSH
if "%choice%"=="3" goto COMMIT_PUSH
if "%choice%"=="4" goto LOG
if "%choice%"=="5" goto CHECKOUT_VIEW
if "%choice%"=="6" goto RESTORE_FILE
if "%choice%"=="7" goto BACK_TO_LATEST
if "%choice%"=="0" goto END
goto MENU

:COMMIT
echo.
set /p msg="اكتب وصف التعديل (مثال: تعديل صفحة الرئيسية): "
git add -A
git commit -m "%msg%"
echo.
echo  ✅ تم حفظ التعديلات بنجاح!
echo.
pause
goto MENU

:PUSH
echo.
echo  جاري الرفع على GitHub...
git push origin main
echo.
echo  ✅ تم الرفع على GitHub!
echo.
pause
goto MENU

:COMMIT_PUSH
echo.
set /p msg="اكتب وصف التعديل: "
git add -A
git commit -m "%msg%"
echo  جاري الرفع على GitHub...
git push origin main
echo.
echo  ✅ تم الحفظ والرفع بنجاح!
echo.
pause
goto MENU

:LOG
echo.
echo  آخر 20 تعديل:
echo  ─────────────────────────────────────────
git log --oneline --graph --decorate -20
echo  ─────────────────────────────────────────
echo.
pause
goto MENU

:CHECKOUT_VIEW
echo.
echo  آخر 15 تعديل:
git log --oneline -15
echo.
set /p hash="اكتب الـ Hash اللي عايز تشوفه (أول 7 أحرف): "
git checkout %hash%
echo.
echo  ⚠️  أنت الآن في نسخة قديمة - مشاهدة فقط
echo  للرجوع للأحدث: اختار [7] من القائمة
echo.
pause
goto MENU

:RESTORE_FILE
echo.
echo  آخر 15 تعديل:
git log --oneline -15
echo.
set /p hash="اكتب الـ Hash اللي عايز ترجع منه: "
set /p file="اكتب اسم الملف اللي عايز ترجعه (مثال: views.py): "
git checkout %hash% -- %file%
echo.
echo  ✅ تم استرجاع %file% من النسخة %hash%
echo  ملاحظة: الملف اتعدل في الـ working directory
echo  لو عايز تحفظ التغيير اعمل commit (اختار 1)
echo.
pause
goto MENU

:BACK_TO_LATEST
echo.
git checkout main
echo.
echo  ✅ رجعت للنسخة الأحدث!
echo.
pause
goto MENU

:END
set GIT_DIR=
set GIT_WORK_TREE=
echo.
