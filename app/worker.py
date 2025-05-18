# app/worker.py
import pika
import json
import time
from models import SessionLocal, InAppNotification
from twilio.rest import Client
import os
import smtplib
from email.mime.text import MIMEText

MAX_RETRIES = 3

def send_email(to, message):
    try:
        smtp_host = os.getenv("EMAIL_HOST")
        smtp_port = int(os.getenv("EMAIL_PORT", 587))
        smtp_user = os.getenv("EMAIL_USERNAME")
        smtp_pass = os.getenv("EMAIL_PASSWORD")

        msg = MIMEText(message)
        msg["Subject"] = "Notification"
        msg["From"] = smtp_user
        msg["To"] = to

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, [to], msg.as_string())
        print(f"[EMAIL] Sent to: {to} | Message: {message}")
    except Exception as e:
        print(f"[EMAIL ERROR] {e}")

def send_sms(to, message):
    try:
        account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        auth_token = os.getenv("TWILIO_AUTH_TOKEN")
        messaging_service_sid = os.getenv("TWILIO_MESSAGING_SERVICE_SID")  # Add this to your .env
        client = Client(account_sid, auth_token)
        message = client.messages.create(
            body=message,
            messaging_service_sid=messaging_service_sid,
            to=to
        )
        print(f"[SMS] Sent via Twilio Messaging Service to: {to} | SID: {message.sid}")
    except Exception as e:
        print(f"[SMS ERROR] {e}")

def send_inapp(to, message, user_id):
    db = SessionLocal()
    db_notif = InAppNotification(
        user_id=user_id,
        message=message,
        type="inapp"
    )
    db.add(db_notif)
    db.commit()
    db.close()
    print(f"[IN-APP] To: {to} | Message: {message}")

def callback(ch, method, properties, body):
    try:
        notif = json.loads(body)
        notif_type = notif['type']
        to = notif['to']
        message = notif['message']
        retries = notif.get('retries', 0)

        if notif_type == "email":
            send_email(to, message)
        elif notif_type == "sms":
            send_sms(to, message)
        elif notif_type == "inapp":
            send_inapp(to, message, notif['user_id'])
        else:
            raise Exception(f"Unsupported notification type: {notif_type}")

        ch.basic_ack(delivery_tag=method.delivery_tag)

    except Exception as e:
        print(f"[ERROR] {e}")
        notif = json.loads(body)
        retries = notif.get("retries", 0)
        if retries < MAX_RETRIES:
            notif["retries"] = retries + 1
            time.sleep(2)  # Optional backoff
            ch.basic_ack(delivery_tag=method.delivery_tag)
            ch.basic_publish(
                exchange='',
                routing_key='notifications',
                body=json.dumps(notif),
                properties=pika.BasicProperties(delivery_mode=2)
            )
            print(f"[RETRY] Retrying ({notif['retries']}/{MAX_RETRIES})")
        else:
            print(f"[FAILED] Max retries reached for notification: {notif}")
            ch.basic_ack(delivery_tag=method.delivery_tag)

def main():
    while True:
        try:
            connection = pika.BlockingConnection(pika.ConnectionParameters("rabbitmq"))
            break
        except pika.exceptions.AMQPConnectionError:
            print("Waiting for RabbitMQ...")
            time.sleep(2)
    channel = connection.channel()
    channel.queue_declare(queue="notifications", durable=True)
    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(queue="notifications", on_message_callback=callback)

    print("[WORKER] Waiting for messages...")
    channel.start_consuming()

if __name__ == "__main__":
    main()
