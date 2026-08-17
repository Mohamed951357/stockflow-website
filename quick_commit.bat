@echo off
chcp 65001 >nul
cd /d "d:\StockFlow_Collection\ملفات الموقع"
git add templates/community_chat.html
git commit -m "إعادة تصميم صفحة الشات لتشبه تطبيق واتساب"
git push origin main
echo.
echo ✅ تم الحفظ والرفع بنجاح!
pause
