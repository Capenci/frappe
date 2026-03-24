# import requests, json

# s = requests.Session()
# s.post("http://mysite.localhost:8000/api/method/login", data={"usr":"Administrator","pwd":"admin"})

# # Create playbook
# playbook = {
#     "doctype":"SOAR Playbook",
#     "__newname":"PB-ALERT-ENRICH-001",
#     "title":"Alert Enrichment Playbook",
#     "is_active":1,
#     "trigger_type":"Event",
#     "trigger_doctype":"SOAR Alert",
#     "trigger_event":"after_insert",
#     "version":1,
#     "nodes":[
#         {"doctype":"SOAR Playbook Node","node_id":"n_start","node_name":"Alert Triggered","node_type":"Start","position_x":400,"position_y":50},
#         {"doctype":"SOAR Playbook Node","node_id":"n_read","node_name":"Read Alert Data","node_type":"Action","action_type":"Script","position_x":400,"position_y":180,
#          "script":"doc = input_data.get('doc', {})\nresult = {'source_ip': doc.get('source_ip',''), 'severity': doc.get('severity',''), 'title': doc.get('title','')}\ncontext['source_ip'] = doc.get('source_ip','')"},
#         {"doctype":"SOAR Playbook Node","node_id":"n_check","node_name":"Has Source IP?","node_type":"Condition","position_x":400,"position_y":310},
#         {"doctype":"SOAR Playbook Node","node_id":"n_enrich","node_name":"Enrich via API","node_type":"Action","action_type":"Script","position_x":280,"position_y":440,
#          "script":"ip = context.get('source_ip','')\nresult = {'ip': ip, 'enrichment': {'reputation': 'malicious' if ip.startswith('185.') else 'clean', 'country': 'US', 'asn': 'AS12345'}}"},
#         {"doctype":"SOAR Playbook Node","node_id":"n_skip","node_name":"Skip Enrichment","node_type":"Action","action_type":"Script","position_x":560,"position_y":440,
#          "script":"result = {'skipped': True, 'reason': 'No source IP available'}"},
#         {"doctype":"SOAR Playbook Node","node_id":"n_end","node_name":"Done","node_type":"End","position_x":400,"position_y":570}
#     ],
#     "edges":[
#         {"doctype":"SOAR Playbook Edge","from_node":"n_start","to_node":"n_read"},
#         {"doctype":"SOAR Playbook Edge","from_node":"n_read","to_node":"n_check"},
#         {"doctype":"SOAR Playbook Edge","from_node":"n_check","to_node":"n_enrich","label":"Yes","condition":"context.get('source_ip')"},
#         {"doctype":"SOAR Playbook Edge","from_node":"n_check","to_node":"n_skip","label":"No","condition":"not context.get('source_ip')"},
#         {"doctype":"SOAR Playbook Edge","from_node":"n_enrich","to_node":"n_end"},
#         {"doctype":"SOAR Playbook Edge","from_node":"n_skip","to_node":"n_end"}
#     ]
# }

# r = s.post("http://mysite.localhost:8000/api/resource/SOAR Playbook", json={"data":json.dumps(playbook)})
# if r.status_code == 200:
#     print(f"Playbook created: {r.json()['data']['name']}")
# else:
#     print(f"Playbook FAIL {r.status_code}: {r.text[:300]}")



import requests, json

s = requests.Session()
s.post("http://mysite.localhost:8000/api/method/login", data={"usr":"Administrator","pwd":"admin"})

# Build the update payload with correct scripts
nodes = [
    {"node_id":"n_start","node_name":"Alert Triggered","node_type":"Start","position_x":400,"position_y":50},
    {"node_id":"n_read","node_name":"Read Alert Data","node_type":"Action","action_type":"Script","position_x":400,"position_y":180,
     "script":"doc = input_data.get('doc', {})\nresult = {'source_ip': doc.get('source_ip',''), 'severity': doc.get('severity',''), 'title': doc.get('title','')}\ncontext['source_ip'] = doc.get('source_ip','')"},
    {"node_id":"n_check","node_name":"Has Source IP?","node_type":"Condition","position_x":400,"position_y":310},
    {"node_id":"n_enrich","node_name":"Enrich via API","node_type":"Action","action_type":"Script","position_x":280,"position_y":440,
     "script":"ip = context.get('source_ip','')\nresult = {'ip': ip, 'enrichment': {'reputation': 'malicious' if ip.startswith('185.') else 'clean', 'country': 'US', 'asn': 'AS12345'}}"},
    {"node_id":"n_skip","node_name":"Skip Enrichment","node_type":"Action","action_type":"Script","position_x":560,"position_y":440,
     "script":"result = {'skipped': True, 'reason': 'No source IP available'}"},
    {"node_id":"n_end","node_name":"Done","node_type":"End","position_x":400,"position_y":570}
]

edges = [
    {"from_node":"n_start","to_node":"n_read"},
    {"from_node":"n_read","to_node":"n_check"},
    {"from_node":"n_check","to_node":"n_enrich","label":"Yes","condition":"context.get('source_ip')"},
    {"from_node":"n_check","to_node":"n_skip","label":"No","condition":"not context.get('source_ip')"},
    {"from_node":"n_enrich","to_node":"n_end"},
    {"from_node":"n_skip","to_node":"n_end"}
]

r = s.put("http://mysite.localhost:8000/api/resource/SOAR Playbook/PB-ALERT-ENRICH-001",
    json={"nodes": nodes, "edges": edges})

if r.status_code == 200:
    data = r.json()["data"]
    print("Updated nodes:")
    for n in data["nodes"]:
        print(f"  {n['node_id']}: script={'yes' if n.get('script') else 'no'}")
else:
    print(f"FAIL {r.status_code}: {r.text[:400]}")