#!/usr/bin/env python3
"""
Create uploads folder structure for community media
"""
import os

def create_folders():
    base_path = os.path.dirname(os.path.abspath(__file__))
    uploads_path = os.path.join(base_path, 'static', 'uploads', 'community')
    
    try:
        os.makedirs(uploads_path, exist_ok=True)
        print(f"✅ Created folder: {uploads_path}")
        
        # Create .gitkeep to preserve folder in git
        gitkeep_path = os.path.join(uploads_path, '.gitkeep')
        with open(gitkeep_path, 'w') as f:
            f.write('')
        print(f"✅ Created .gitkeep file")
        
        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

if __name__ == '__main__':
    create_folders()
