with open('/Users/gonzo/Desktop/V2/lyudyn-iskun-v2/docker-compose.yml', 'r') as f:
    content = f.read()

api_service = """
  web_api:
    build: .
    restart: unless-stopped
    command: uvicorn api.main:app --host 0.0.0.0 --port 80
    ports:
      - "80:80"
    env_file: .env
    depends_on:
      - db
"""

if 'web_api:' not in content:
    # Append it to the services block.
    content = content.replace("volumes:\n  redis_data:", api_service + "\nvolumes:\n  redis_data:")
    with open('/Users/gonzo/Desktop/V2/lyudyn-iskun-v2/docker-compose.yml', 'w') as f:
        f.write(content)
