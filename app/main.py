# app/main.py
from fastapi import FastAPI, Depends
from pydantic import BaseModel
import pika
import json
from sqlalchemy.orm import Session
from models import Base, engine, SessionLocal, InAppNotification

# Create tables
Base.metadata.create_all(bind=engine)

app = FastAPI()

class Notification(BaseModel):
    user_id: int
    type: str  # "email", "sms", "inapp"
    to: str
    message: str

def get_channel():
    connection = pika.BlockingConnection(pika.ConnectionParameters("rabbitmq"))
    channel = connection.channel()
    channel.queue_declare(queue="notifications", durable=True)
    return connection, channel

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.post("/notifications")
def send_notification(notification: Notification, db: Session = Depends(get_db)):
    connection, channel = get_channel()
    body = json.dumps(notification.dict())
    channel.basic_publish(
        exchange='',
        routing_key='notifications',
        body=body,
        properties=pika.BasicProperties(delivery_mode=2)  # make message persistent
    )
    connection.close()
    # For in-app, store in DB immediately
    if notification.type == "inapp":
        db_notif = InAppNotification(
            user_id=notification.user_id,
            message=notification.message,
            type=notification.type
        )
        db.add(db_notif)
        db.commit()
        db.refresh(db_notif)
    return {"status": "queued"}

@app.get("/users/{user_id}/notifications")
def get_user_notifications(user_id: int, db: Session = Depends(get_db)):
    notifs = db.query(InAppNotification).filter(InAppNotification.user_id == user_id).all()
    return [
        {"id": n.id, "user_id": n.user_id, "message": n.message, "type": n.type}
        for n in notifs
    ]

@app.get("/")
def root():
    return {"message": "Notification Service is running!"}