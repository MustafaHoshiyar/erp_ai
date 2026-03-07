import os
import requests
from dotenv import load_dotenv

load_dotenv()

url = os.getenv('ERP_URL') + '/api/method/frappe.utils.change_log.get_versions'
headers = {
    'Authorization': 'token ' + os.getenv('ERP_API_KEY') + ':' + os.getenv('ERP_API_SECRET'),
    'Content-Type': 'application/json'
}

response = requests.get(url, headers=headers)
print("Status Code:", response.status_code)
with open("output.txt", "w") as f:
    f.write(response.text)
print("Saved to output.txt")
