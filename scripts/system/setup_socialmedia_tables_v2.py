#!/usr/bin/env python3
"""
Create Social Media tables in Baserow via API
Uses JWT authentication for schema operations
"""

import requests
import json
import time
import sys

# Configuration
BASEROW_URL = "http://localhost:8085"
EMAIL = "jonnybenzin@gmail.com"
PASSWORD = "MaGGan99@"
DATABASE_ID = 110

def get_jwt_token():
    """Login and get JWT token"""
    print("  Getting JWT token...")
    resp = requests.post(
        f"{BASEROW_URL}/api/user/token-auth/",
        headers={"Content-Type": "application/json"},
        json={"email": EMAIL, "password": PASSWORD}
    )
    if resp.status_code == 200:
        token = resp.json()["access_token"]
        print("  ✓ JWT token obtained")
        return token
    else:
        print(f"  ✗ Login failed: {resp.status_code} - {resp.text}")
        sys.exit(1)

def get_headers(jwt_token):
    return {
        "Authorization": f"JWT {jwt_token}",
        "Content-Type": "application/json"
    }

def create_table(jwt_token, name):
    """Create a new table in the database"""
    resp = requests.post(
        f"{BASEROW_URL}/api/database/tables/database/{DATABASE_ID}/",
        headers=get_headers(jwt_token),
        json={"name": name}
    )
    if resp.status_code in [200, 201]:
        table = resp.json()
        print(f"  ✓ Created table: {name} (ID: {table['id']})")
        return table
    else:
        print(f"  ✗ Error creating {name}: {resp.status_code} - {resp.text}")
        return None

def delete_table(jwt_token, table_id):
    """Delete a table"""
    resp = requests.delete(
        f"{BASEROW_URL}/api/database/tables/{table_id}/",
        headers=get_headers(jwt_token)
    )
    if resp.status_code in [200, 204]:
        print(f"  ✓ Deleted table ID: {table_id}")
        return True
    else:
        print(f"  ✗ Error deleting table: {resp.status_code}")
        return False

def create_field(jwt_token, table_id, name, field_type, **kwargs):
    """Create a field in a table"""
    data = {
        "name": name,
        "type": field_type,
        **kwargs
    }
    resp = requests.post(
        f"{BASEROW_URL}/api/database/fields/table/{table_id}/",
        headers=get_headers(jwt_token),
        json=data
    )
    if resp.status_code in [200, 201]:
        print(f"    + {name} ({field_type})")
        return resp.json()
    else:
        print(f"    ✗ Error: {name} - {resp.status_code} - {resp.text}")
        return None

def delete_default_fields(jwt_token, table_id):
    """Delete the default fields that Baserow creates"""
    resp = requests.get(
        f"{BASEROW_URL}/api/database/fields/table/{table_id}/",
        headers=get_headers(jwt_token)
    )
    if resp.status_code == 200:
        for field in resp.json():
            if field['name'] in ['Name', 'Notes', 'Active']:
                delete_resp = requests.delete(
                    f"{BASEROW_URL}/api/database/fields/{field['id']}/",
                    headers=get_headers(jwt_token)
                )
                if delete_resp.status_code in [200, 204]:
                    print(f"    - Deleted default field: {field['name']}")

def get_table_id_by_name(jwt_token, name):
    """Get table ID by name"""
    resp = requests.get(
        f"{BASEROW_URL}/api/database/tables/database/{DATABASE_ID}/",
        headers=get_headers(jwt_token)
    )
    if resp.status_code == 200:
        for table in resp.json():
            if table['name'] == name:
                return table['id']
    return None

def create_sm_adaptations(jwt_token, content_table_id):
    """Create SM_adaptations table"""
    print("\n Creating SM_adaptations...")
    table = create_table(jwt_token, "SM_adaptations")
    if not table:
        return None
    
    table_id = table['id']
    time.sleep(0.3)
    
    delete_default_fields(jwt_token, table_id)
    
    # Fields
    create_field(jwt_token, table_id, "content_link", "link_row", link_row_table_id=content_table_id)
    create_field(jwt_token, table_id, "content_id", "text")
    create_field(jwt_token, table_id, "platform", "single_select",
                 select_options=[
                     {"value": "linkedin", "color": "blue"},
                     {"value": "instagram", "color": "purple"},
                     {"value": "x", "color": "light-gray"},
                     {"value": "tiktok", "color": "red"}
                 ])
    create_field(jwt_token, table_id, "caption_adapted", "long_text")
    create_field(jwt_token, table_id, "format", "single_select",
                 select_options=[
                     {"value": "post", "color": "blue"},
                     {"value": "carousel", "color": "purple"},
                     {"value": "reel", "color": "red"},
                     {"value": "story", "color": "yellow"},
                     {"value": "thread", "color": "light-gray"},
                     {"value": "article", "color": "green"}
                 ])
    create_field(jwt_token, table_id, "hashtags", "text")
    create_field(jwt_token, table_id, "challenger_notes", "long_text")
    create_field(jwt_token, table_id, "proofreader_notes", "long_text")
    create_field(jwt_token, table_id, "status", "single_select",
                 select_options=[
                     {"value": "draft", "color": "light-gray"},
                     {"value": "review", "color": "yellow"},
                     {"value": "ready", "color": "green"},
                     {"value": "scheduled", "color": "blue"},
                     {"value": "published", "color": "dark-blue"}
                 ])
    create_field(jwt_token, table_id, "version", "number", number_decimal_places=0)
    create_field(jwt_token, table_id, "created_at", "created_on")
    create_field(jwt_token, table_id, "updated_at", "last_modified")
    
    return table_id

def create_sm_assets(jwt_token, content_table_id):
    """Create SM_assets table"""
    print("\n Creating SM_assets...")
    table = create_table(jwt_token, "SM_assets")
    if not table:
        return None
    
    table_id = table['id']
    time.sleep(0.3)
    
    delete_default_fields(jwt_token, table_id)
    
    # Fields
    create_field(jwt_token, table_id, "content_link", "link_row", link_row_table_id=content_table_id)
    create_field(jwt_token, table_id, "content_id", "text")
    create_field(jwt_token, table_id, "asset_type", "single_select",
                 select_options=[
                     {"value": "photo", "color": "blue"},
                     {"value": "gif", "color": "purple"},
                     {"value": "graphic", "color": "green"},
                     {"value": "ai_image", "color": "red"},
                     {"value": "screenshot", "color": "yellow"},
                     {"value": "video", "color": "orange"}
                 ])
    create_field(jwt_token, table_id, "source", "single_select",
                 select_options=[
                     {"value": "pexels", "color": "green"},
                     {"value": "pixabay", "color": "blue"},
                     {"value": "gifer", "color": "purple"},
                     {"value": "penpot", "color": "yellow"},
                     {"value": "comfyui", "color": "red"},
                     {"value": "mixpost", "color": "orange"},
                     {"value": "manual", "color": "light-gray"}
                 ])
    create_field(jwt_token, table_id, "mixpost_url", "url")
    create_field(jwt_token, table_id, "source_url", "url")
    create_field(jwt_token, table_id, "file_name", "text")
    create_field(jwt_token, table_id, "description", "long_text")
    create_field(jwt_token, table_id, "platforms", "multiple_select",
                 select_options=[
                     {"value": "linkedin", "color": "blue"},
                     {"value": "instagram", "color": "purple"},
                     {"value": "x", "color": "light-gray"},
                     {"value": "tiktok", "color": "red"}
                 ])
    create_field(jwt_token, table_id, "status", "single_select",
                 select_options=[
                     {"value": "pending", "color": "yellow"},
                     {"value": "ready", "color": "green"}
                 ])
    create_field(jwt_token, table_id, "created_at", "created_on")
    
    return table_id

def create_sm_calendar(jwt_token, adaptations_table_id):
    """Create SM_calendar table"""
    print("\n Creating SM_calendar...")
    table = create_table(jwt_token, "SM_calendar")
    if not table:
        return None
    
    table_id = table['id']
    time.sleep(0.3)
    
    delete_default_fields(jwt_token, table_id)
    
    # Fields
    create_field(jwt_token, table_id, "adaptation_link", "link_row", link_row_table_id=adaptations_table_id)
    create_field(jwt_token, table_id, "content_id", "text")
    create_field(jwt_token, table_id, "platform", "single_select",
                 select_options=[
                     {"value": "linkedin", "color": "blue"},
                     {"value": "instagram", "color": "purple"},
                     {"value": "x", "color": "light-gray"},
                     {"value": "tiktok", "color": "red"}
                 ])
    create_field(jwt_token, table_id, "publish_date", "date")
    create_field(jwt_token, table_id, "publish_time", "text")
    create_field(jwt_token, table_id, "status", "single_select",
                 select_options=[
                     {"value": "scheduled", "color": "yellow"},
                     {"value": "published", "color": "green"},
                     {"value": "skipped", "color": "light-gray"}
                 ])
    create_field(jwt_token, table_id, "platform_url", "url")
    create_field(jwt_token, table_id, "published_at", "date")
    create_field(jwt_token, table_id, "created_at", "created_on")
    
    return table_id

def create_sm_performance(jwt_token, calendar_table_id):
    """Create SM_performance table"""
    print("\n Creating SM_performance...")
    table = create_table(jwt_token, "SM_performance")
    if not table:
        return None
    
    table_id = table['id']
    time.sleep(0.3)
    
    delete_default_fields(jwt_token, table_id)
    
    # Fields
    create_field(jwt_token, table_id, "calendar_link", "link_row", link_row_table_id=calendar_table_id)
    create_field(jwt_token, table_id, "content_id", "text")
    create_field(jwt_token, table_id, "platform", "single_select",
                 select_options=[
                     {"value": "linkedin", "color": "blue"},
                     {"value": "instagram", "color": "purple"},
                     {"value": "x", "color": "light-gray"},
                     {"value": "tiktok", "color": "red"}
                 ])
    create_field(jwt_token, table_id, "impressions", "number", number_decimal_places=0)
    create_field(jwt_token, table_id, "engagements", "number", number_decimal_places=0)
    create_field(jwt_token, table_id, "likes", "number", number_decimal_places=0)
    create_field(jwt_token, table_id, "comments", "number", number_decimal_places=0)
    create_field(jwt_token, table_id, "shares", "number", number_decimal_places=0)
    create_field(jwt_token, table_id, "saves", "number", number_decimal_places=0)
    create_field(jwt_token, table_id, "clicks", "number", number_decimal_places=0)
    create_field(jwt_token, table_id, "engagement_rate", "number", number_decimal_places=2)
    create_field(jwt_token, table_id, "recorded_at", "date")
    create_field(jwt_token, table_id, "notes", "long_text")
    
    return table_id

def main():
    print("=" * 60)
    print("BASEROW SOCIAL MEDIA - CREATE REMAINING TABLES")
    print("=" * 60)
    
    # Step 1: Get JWT token
    print("\n Step 1: Authentication")
    jwt_token = get_jwt_token()
    
    # Step 2: Delete test table if exists
    print("\n Step 2: Cleanup test table")
    test_table_id = get_table_id_by_name(jwt_token, "SM_test_delete")
    if test_table_id:
        delete_table(jwt_token, test_table_id)
    else:
        print("  No test table to delete")
    
    # Step 3: Get existing table IDs
    print("\n Step 3: Finding existing tables")
    content_id = get_table_id_by_name(jwt_token, "SM_content")
    adaptations_id = get_table_id_by_name(jwt_token, "SM_adaptations")
    
    print(f"  SM_content ID: {content_id}")
    print(f"  SM_adaptations ID: {adaptations_id}")
    
    if not content_id:
        print("\n  ✗ Error: SM_content must exist first!")
        sys.exit(1)
    
    # Step 4: Create remaining tables
    print("\n Step 4: Creating remaining tables")
    
    # Create SM_adaptations if it doesn't exist
    if not adaptations_id:
        adaptations_id = create_sm_adaptations(jwt_token, content_id)
    else:
        print(f"\n  SM_adaptations already exists (ID: {adaptations_id})")
    
    assets_id = create_sm_assets(jwt_token, content_id)
    calendar_id = create_sm_calendar(jwt_token, adaptations_id)
    performance_id = create_sm_performance(jwt_token, calendar_id)
    
    # Summary
    print("\n" + "=" * 60)
    print(" COMPLETE!")
    print("=" * 60)
    
    # Get all table IDs for reference
    strategy_id = get_table_id_by_name(jwt_token, "SM_strategy")
    
    print(f"""
 All Table IDs (save for API integration):
 
   SM_strategy:    {strategy_id}
   SM_content:     {content_id}
   SM_adaptations: {adaptations_id}
   SM_assets:      {assets_id}
   SM_calendar:    {calendar_id}
   SM_performance: {performance_id}
   
 Next steps:
 1. Check tables in Baserow UI
 2. Update knowledge-api.py with table IDs
 3. Create Dify agents
""")

if __name__ == "__main__":
    main()
