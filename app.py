import logging
import asyncio
from queue import Queue
import os
import requests
import smtplib
from email.message import EmailMessage
from uvicorn import Config, Server
from logging.handlers import QueueHandler, QueueListener
from quart import Quart, request, jsonify, render_template
from nessclient import ArmingState, ArmingMode, BaseEvent
from nessclient.client import Client

# Configure logging
log_queue = Queue()
queue_handler = QueueHandler(log_queue)
handler = logging.StreamHandler()
listener = QueueListener(log_queue, handler)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', handlers=[queue_handler])
listener.start()

DISCORD_WEBHOOK_URL = os.getenv('NESS_DISCORD_WEBHOOK_URL', 'https://discord.com/api/webhooks/1234567890/ABCDEFGHIJKLMN0123456789')
AVATAR_URL = os.getenv('NESS_AVATAR_URL', '')
IMAGE_URL = os.getenv('NESS_IMAGE_URL', '')
HOST = os.getenv('NESS_HOST', '192.168.0.0')
HOSTPORT = int(os.getenv('NESS_HPORT', 23))
PORT = int(os.getenv('NESS_PORT', 5000))
SMTP_SERVER = os.getenv('NESS_SMTP_SERVER', 'smtp.gmail.com')
SMTP_PORT = int(os.getenv('NESS_SMTP_PORT', 587))
SMTP_USER = os.getenv('NESS_SMTP_USER', '')
SMTP_FROM = os.getenv('NESS_SMTP_FROM', '')
SMTP_PASS = os.getenv('NESS_SMTP_PASS', '')
SMTP_TLS = os.getenv('NESS_SMTP_TLS', True)
EMAILS = os.getenv('NESS_EMAILS', '').split(',')
HOSTNAME = os.getenv('NESS_HOSTNAME', '0.0.0.0')



app = Quart(__name__, static_folder='static')
events = list()
client = Client(host=HOST, port=HOSTPORT)

@app.route('/')
async def keypad():
    return await render_template('keypad.html')

@app.route('/arm_away', methods=['POST'])
async def arm_away():
    data = await request.json
    if data is None:
        return jsonify({"error": "Invalid JSON"}), 400
    code = data.get('code')
    await client.arm_away(code)
    return jsonify({"status": "armed away"}), 200

@app.route('/disarm', methods=['POST'])
async def disarm():
    data = await request.json
    if data is None:
        return jsonify({"error": "Invalid JSON"}), 400
    code = data.get('code')
    await client.disarm(code)
    return jsonify(), 200

@app.route('/heartbeat', methods=['GET'])
async def get_state():
    state = await get_current_state()

    # Convert the arming state to a JSON serializable format
    arming_state = state.get("arming_state")
    zones = state.get("zones")
    if isinstance(arming_state, ArmingState):
        arming_state = str(arming_state)  # or arming_state.to_string() or str(arming_state)

    return jsonify({
        'arming_state': arming_state,
        'zones': zones
    }), 200


async def get_current_state():
    return {
        "arming_state": client.alarm.arming_state,
        "zones": client.alarm.zones,
    }


async def send_email(subject, content):
    message = ("Subject: {}\n\n{}".format(subject, content))
    server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
    message = EmailMessage()
    message["From"] = SMTP_FROM
    message["Subject"] = subject
    message.set_content(content)
    try:
        server.ehlo()
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        for (email) in EMAILS:
            message["To"] = email
            server.send_message(message)
    except Exception as e:
        logging.error(f"Failed to send email: {e}")

    finally:
        server.quit()

async def main():

    @client.on_zone_change
    def on_zone_change(zone: int, triggered: bool) -> None:
        logging.info(f"Zone {zone} changed to {triggered}")

    @client.on_state_change
    def on_state_change(state: ArmingState, arming_mode: ArmingMode | None) -> None:
        statevalue = state.value
        modevalue = arming_mode.value if arming_mode else "NONE"
        # Send alert to Discord webhook
        message = {
          "embeds": [
            {
              "title": f"Alarm State Changed to: {statevalue}",
              "description": f"Arming Mode: {modevalue}",
              "color": 16711680,
              "thumbnail": {
                "url": f"{IMAGE_URL}/{statevalue.lower()}.png"
              }
            }
          ],
          "username": "NESS",
          "avatar_url": f"{AVATAR_URL}",
          "attachments": []
        }
        response = requests.post(DISCORD_WEBHOOK_URL, json=message)
        if response.status_code != 204:
            logging.error(f"Failed to send Discord webhook: {response.status_code} {response.text}")
        # Send alert via email ONLY if ArmingState.TRIGGERED
        if state == ArmingState.TRIGGERED:
            subject = "Alarm Triggered"
            content = f"The alarm has been triggered. Current state: {state} (mode: {arming_mode})"
            asyncio.create_task(send_email(subject, content))

    @client.on_event_received
    def on_event_received(event: BaseEvent) -> None:
        logging.info(event)

    config = Config(app, host=HOSTNAME, port=PORT)
    server = Server(config)

    await asyncio.gather(
        client.keepalive(),
        client.update(),
        server.serve()
    )

if __name__ == '__main__':
    asyncio.run(main())