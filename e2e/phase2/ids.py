"""Fixed fake identifiers shared by the seeds and the driver (not secrets)."""

CONNECTION_IDS = {
    "instagram": "aaaaaaaa-0000-4000-8000-000000000001",
    "whatsapp": "aaaaaaaa-0000-4000-8000-000000000002",
    "messenger": "aaaaaaaa-0000-4000-8000-000000000003",
}
# Many channel identifiers: delegation ON and OFF rows for each platform.
MANY_CHANNELS = {
    ("instagram", True): "17840e2e0001",
    ("instagram", False): "17840e2e0002",
    ("whatsapp", True): "e2ewa0001",
    ("whatsapp", False): "e2ewa0002",
    ("messenger", True): "e2efb0001",
    ("messenger", False): "e2efb0002",
}
SAAS_URL = "http://saas-api:8000"
MANY_URL = "http://many-api:8000"
