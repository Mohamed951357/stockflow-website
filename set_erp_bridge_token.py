import sys
from datetime import datetime

from app import app
from models import db, SystemSetting


def main():
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        print("Usage: python set_erp_bridge_token.py YOUR_TOKEN")
        raise SystemExit(1)

    token = sys.argv[1].strip()

    with app.app_context():
        setting = SystemSetting.query.filter_by(setting_key='erp_bridge_token').first()
        if setting:
            setting.setting_value = token
            setting.last_updated = datetime.utcnow()
        else:
            setting = SystemSetting(
                setting_key='erp_bridge_token',
                setting_value=token,
                last_updated=datetime.utcnow()
            )
            db.session.add(setting)

        db.session.commit()
        print("erp_bridge_token saved successfully.")


if __name__ == '__main__':
    main()
