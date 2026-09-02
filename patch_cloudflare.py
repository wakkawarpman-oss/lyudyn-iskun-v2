with open('/Users/gonzo/Desktop/V2/lyudyn-iskun-v2/docker-compose.yml', 'r') as f:
    content = f.read()

cloudflare_service = """
  cloudflared:
    image: cloudflare/cloudflared:latest
    command: tunnel --url http://web_api:80
    restart: unless-stopped
    depends_on:
      - web_api
"""

if 'cloudflared:' not in content:
    content = content.replace("volumes:\n  redis_data:", cloudflare_service + "\nvolumes:\n  redis_data:")
    with open('/Users/gonzo/Desktop/V2/lyudyn-iskun-v2/docker-compose.yml', 'w') as f:
        f.write(content)
