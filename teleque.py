import datetime
import logging
import os
import random
import threading
import uuid
from datetime import timedelta
from logging import DEBUG
from typing import List

import time
from peewee import *
from ruamel.yaml.main import YAML
from telegram.bot import Bot
from telegram.ext.commandhandler import CommandHandler
from telegram.ext.filters import Filters
from telegram.ext.messagehandler import MessageHandler
from telegram.ext.updater import Updater
from telegram.update import Update


def get_setting(setting):
    return YAML().load(open('config.yml').read()).get(setting)


start_message = "Доступные команды\n/queue - отображает колличество постов в очереди\n" \
                "/setinterval [min] - устанавливает интервал между публикациями(в минутах)\n" \
                "/interval - отображает текущий интервал между публикациями(в минутах)\n" \
                "Для того чтобы добавить фотографию в очередь, просто отправь её мне"

token = get_setting('token')
publication_interval = get_setting('publication_interval')
publication_chanel = get_setting('publication_chanel')
admins = get_setting('admin_users')

db = SqliteDatabase('teleque.db')

bot_reference = ...


class Publication(Model):
    id = PrimaryKeyField()
    telegram_id = CharField(null=False)
    file_path = CharField(null=False)
    published = BooleanField(default=False)

    class Meta:
        database = db


publication_queue: List[Publication] = []

# logging
os.mkdir('logs') if not os.path.exists('logs') else None
date = datetime.date.today()
now_time = datetime.datetime.now()
log_file_name = f"bot_{date}_{now_time.hour}-{now_time.minute}-{now_time.second}.log"
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    filename='/'.join(['logs', log_file_name]), level=DEBUG)
logger = logging.getLogger(__name__)
logger.isEnabledFor(99)


def start(bot: Bot, update: Update):
    bot.send_message(
        update.effective_chat.id,
        text=start_message
    )


def queue(bot: Bot, update: Update):
    queue_len = len(publication_queue)
    bot.send_message(
        update.effective_chat.id,
        text=f'Сейчас в очереди {queue_len} фотографий'
    )


def interval(bot: Bot, update: Update):
    bot.send_message(
        update.effective_chat.id,
        text=f'Текущий интервал между публикациями {publication_interval} минут'
    )


def set_interval(bot: Bot, update: Update):
    global publication_interval
    command = update.effective_message.text
    trimmed_command = command.replace('/setinterval', '').strip()
    if trimmed_command:
        try:
            publication_interval = int(trimmed_command)
            bot.send_message(
                update.effective_chat.id,
                text=f'Интервал установлен на {publication_interval} минут'
            )
        except ValueError:
            bot.send_message(
                update.effective_chat.id,
                text='Введите корректное значение интервала публикаций, например /setinterval 15'
            )
    else:
        bot.send_message(
            update.effective_chat.id,
            text='Введите корректное значение интервала публикаций, например /setinterval 15'
        )


def _save_file(file_id):
    bot = bot_reference
    img_dir = 'images'
    while 1:
        if not os.path.exists(img_dir):
            os.mkdir(img_dir)
        image_identifier = str(uuid.uuid4())
        sub_dir = image_identifier.split('-')[:1][0]
        sub_dir_path = os.path.join(img_dir, sub_dir)
        if not os.path.exists(sub_dir_path):
            os.mkdir(sub_dir_path)
        file_name = f'{"".join(image_identifier.split("-")[1:])}.jpg'
        file_path = os.path.normpath(os.path.join(sub_dir_path, file_name))
        if not os.path.exists(file_path):
            file = open(file=file_path, mode='wb')
            image = bot.get_file(file_id=file_id)
            image.download(out=file)
            file.close()
            break
        else:
            continue
    return file_path


def _round_publication_date(date: datetime.datetime):
    if date.minute > 30:
        return date + datetime.timedelta(minutes=60 - date.minute) - datetime.timedelta(seconds=date.second)
    if date.minute < 30:
        return date + datetime.timedelta(minutes=30 - date.minute) - datetime.timedelta(seconds=date.second)
    else:
        return date - datetime.timedelta(seconds=date.second)


def save_photo(bot: Bot, update: Update):
    file_id = update.message.photo[-1].file_id
    file_path = _save_file(file_id)
    publication = Publication(telegram_id=file_id, file_path=file_path)
    publication.save()
    publication_queue.append(publication)
    bot.send_message(
        update.effective_chat.id,
        text=f'Фотография добавлена в очередь, текущий размер очереди {len(publication_queue)}'
    )


def error(bot, update, error):
    logger.log(99, f'Update {update} caused error {error}')


def process_publication():
    logger.log(99, 'Starting process publication')
    if publication_queue:
        bot = bot_reference
        publication = publication_queue.pop(random.randrange(len(publication_queue)))
        logger.log(99, f'Publishing {publication.id}')
        try:
            bot.send_photo(
                chat_id=publication_chanel,
                photo=open(
                    file=publication.file_path,
                    mode='rb'
                )
            )
            publication.published = True
            publication.save()
            logger.log(99, f'publishing {publication.id} successfully done')
        except Exception as e:
            logger.log(99, f'Exception occured while publishing {publication}, {e}')


def publication_loop(interval):
    logger.log(99, 'Starting publication loop')
    publication_time = _round_publication_date(datetime.datetime.now())
    logger.log(99, f'Next publication time {publication_time}')
    while 1:
        if datetime.datetime.now() >= publication_time:
            process_publication()
            publication_time = publication_time + timedelta(minutes=publication_interval)
            logger.log(99, f'Next publication time {publication_time}')
        time.sleep(interval)


def start_publications():
    if Publication.select().where(Publication.published == False).exists():
        publication_queue.extend(Publication.select().where(Publication.published == False).iterator())
    logger.log(99, 'Starting publication thread')
    publication_thread = threading.Thread(target=publication_loop, args=(10,))
    publication_thread.setName("publication")
    publication_thread.daemon = True
    publication_thread.start()


def main():
    db.create_tables([Publication], safe=True)

    commands_filter = Filters.private & Filters.command & Filters.user(username=admins)
    photo_filter = Filters.private & Filters.photo & Filters.user(username=admins)
    handlers = [
        CommandHandler('start', start, filters=commands_filter),
        CommandHandler('queue', queue, filters=commands_filter),
        CommandHandler('interval', interval, filters=commands_filter),
        CommandHandler('setinterval', set_interval, filters=commands_filter),
        MessageHandler(filters=photo_filter, callback=save_photo)
    ]

    updater = Updater(token)
    dp = updater.dispatcher
    global bot_reference
    bot_reference = updater.bot
    [dp.add_handler(handler) for handler in handlers]
    dp.add_error_handler(error)
    updater.start_polling()
    start_publications()
    updater.idle()


if __name__ == '__main__':
    main()
