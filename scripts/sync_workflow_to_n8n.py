import json
import subprocess

# Đọc file workflow mới nhất
with open('n8n_news_aggregator_workflow.json', 'r', encoding='utf-8') as f:
    wf = json.load(f)

nodes_json = json.dumps(wf.get('nodes', []), ensure_ascii=False)
connections_json = json.dumps(wf.get('connections', {}), ensure_ascii=False)
settings_json = json.dumps(wf.get('settings', {}), ensure_ascii=False)

# Escape single quotes cho SQL
nodes_sql = nodes_json.replace("'", "''")
connections_sql = connections_json.replace("'", "''")
settings_sql = settings_json.replace("'", "''")

sql = f"""
SET search_path TO n8n, public;
UPDATE "workflow_entity"
SET 
  "nodes" = '{nodes_sql}'::json,
  "connections" = '{connections_sql}'::json,
  "settings" = '{settings_sql}'::json,
  "active" = true,
  "updatedAt" = NOW()
WHERE id = 'Niy5Mes3nwtDKK8o';
"""

with open('/tmp/update_n8n_wf.sql', 'w', encoding='utf-8') as f:
    f.write(sql)

print('SQL file created at /tmp/update_n8n_wf.sql')
cmd = "docker compose exec -T postgres psql -U postgres -d automation_data < /tmp/update_n8n_wf.sql"
res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
print("STDOUT:", res.stdout)
print("STDERR:", res.stderr)
if res.returncode == 0:
    print("Successfully synchronized workflow into n8n database and set active=true!")
else:
    print("Error executing SQL:", res.stderr)
