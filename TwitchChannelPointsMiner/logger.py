import json
import logging
import os
import platform
import queue
import sys
from datetime import datetime
from logging.handlers import QueueHandler, QueueListener, TimedRotatingFileHandler
from pathlib import Path

import emoji
import pytz
from colorama import Fore, init

from TwitchChannelPointsMiner.classes.Discord import Discord
from TwitchChannelPointsMiner.classes.Matrix import Matrix
from TwitchChannelPointsMiner.classes.Pushover import Pushover
from TwitchChannelPointsMiner.classes.Settings import Events
from TwitchChannelPointsMiner.classes.Telegram import Telegram
from TwitchChannelPointsMiner.classes.Pushover import Pushover
from TwitchChannelPointsMiner.classes.Gotify import Gotify
from TwitchChannelPointsMiner.classes.Webhook import Webhook
from TwitchChannelPointsMiner.utils import remove_emoji


# Fore: BLACK, RED, GREEN, YELLOW, BLUE, MAGENTA, CYAN, WHITE, RESET.
class ColorPalette(object):
    def __init__(self, **kwargs):
        # Init with default values RESET for all and GREEN and RED only for WIN and LOSE bet
        # Then set args from kwargs
        for k in Events:
            setattr(self, str(k), Fore.RESET)
        setattr(self, "BET_WIN", Fore.GREEN)
        setattr(self, "BET_LOSE", Fore.RED)

        for k in kwargs:
            if k.upper() in dir(self) and getattr(self, k.upper()) is not None:
                if kwargs[k] in [
                    Fore.BLACK,
                    Fore.RED,
                    Fore.GREEN,
                    Fore.YELLOW,
                    Fore.BLUE,
                    Fore.MAGENTA,
                    Fore.CYAN,
                    Fore.WHITE,
                    Fore.RESET,
                ]:
                    setattr(self, k.upper(), kwargs[k])
                elif kwargs[k].upper() in [
                    "BLACK",
                    "RED",
                    "GREEN",
                    "YELLOW",
                    "BLUE",
                    "MAGENTA",
                    "CYAN",
                    "WHITE",
                    "RESET",
                ]:
                    setattr(self, k.upper(), getattr(Fore, kwargs[k].upper()))

    def get(self, key):
        color = getattr(self, str(key)) if str(key) in dir(self) else None
        return Fore.RESET if color is None else color


JSON = 0
TEXT = 1


class LoggerSettings:
    __slots__ = [
        "save",
        "less",
        "console_format",
        "console_level",
        "console_username",
        "time_zone",
        "file_format",
        "file_level",
        "emoji",
        "colored",
        "color_palette",
        "auto_clear",
        "telegram",
        "discord",
        "webhook",
        "matrix",
        "pushover",
        "gotify",
        "username"
    ]

    def __init__(
        self,
        save: bool = True,
        less: bool = False,
        console_format: int = TEXT,
        console_level: int = logging.INFO,
        console_username: bool = False,
        time_zone: str or None = None,
        file_format: int = TEXT,
        file_level: int = logging.DEBUG,
        emoji: bool = platform.system() != "Windows",
        colored: bool = False,
        color_palette: ColorPalette = ColorPalette(),
        auto_clear: bool = True,
        telegram: Telegram or None = None,
        discord: Discord or None = None,
        webhook: Webhook or None = None,
        matrix: Matrix or None = None,
        pushover: Pushover or None = None,
        gotify: Gotify or None = None,
        username: str or None = None
    ):
        self.save = save
        self.less = less
        self.console_format = console_format
        self.console_level = console_level
        self.console_username = console_username
        self.time_zone = time_zone
        self.file_format = file_format
        self.file_level = file_level
        self.emoji = emoji
        self.colored = colored
        self.color_palette = color_palette
        self.auto_clear = auto_clear
        self.telegram = telegram
        self.discord = discord
        self.webhook = webhook
        self.matrix = matrix
        self.pushover = pushover
        self.gotify = gotify
        self.username = username


class JsonFormatter(logging.Formatter):
    """
    Formatter that outputs JSON strings after parsing the LogRecord.

    @param dict fmt_dict: Key: logging format attribute pairs. Defaults to {"message": "message"}.
    @param str time_format: time.strftime() format string. Default: "%Y-%m-%dT%H:%M:%S"
    @param str msec_format: Microsecond formatting. Appended at the end. Default: "%s.%03dZ"
    """

    def __init__(self, fmt_dict: dict = None, time_format: str = "%Y-%m-%dT%H:%M:%S", msec_format: str = "%s.%03dZ"):
        super().__init__()
        self.fmt_dict = fmt_dict if fmt_dict is not None else {"message": "message"}
        self.default_time_format = time_format
        self.default_msec_format = msec_format
        self.datefmt = None

    def usesTime(self) -> bool:
        """
        Overwritten to look for the attribute in the format dict values instead of the fmt string.
        """
        return "asctime" in self.fmt_dict.values()

    def formatMessage(self, record) -> dict:
        """
        Overwritten to return a dictionary of the relevant LogRecord attributes instead of a string.
        KeyError is raised if an unknown attribute is provided in the fmt_dict.
        """
        return {fmt_key: record.__dict__[fmt_val] for fmt_key, fmt_val in self.fmt_dict.items()}

    def format(self, record) -> str:
        """
        Mostly the same as the parent's class method, the difference being that a dict is manipulated and dumped as JSON
        instead of a string.
        """
        record.message = record.getMessage()

        if self.usesTime():
            record.asctime = self.formatTime(record, self.datefmt)

        message_dict = self.formatMessage(record)

        if record.exc_info:
            # Cache the traceback text to avoid converting it multiple times
            # (it's constant anyway)
            if not record.exc_text:
                record.exc_text = self.formatException(record.exc_info)

        if record.exc_text:
            message_dict["exc_info"] = record.exc_text

        if record.stack_info:
            message_dict["stack_info"] = self.formatStack(record.stack_info)

        return json.dumps(message_dict, default=str)


class FileFormatter(logging.Formatter):
    def __init__(self, *, fmt, settings: LoggerSettings, datefmt=None):
        self.settings = settings
        self.timezone = None
        if settings.time_zone:
            try:
                self.timezone = pytz.timezone(settings.time_zone)
                logging.info(f"File logger time zone set to: {self.timezone}")
            except pytz.UnknownTimeZoneError:
                logging.error(
                    f"File logger: invalid time zone: {settings.time_zone}")
        logging.Formatter.__init__(self, fmt=fmt, datefmt=datefmt)

    def formatTime(self, record, datefmt=None):
        if self.timezone:
            dt = datetime.fromtimestamp(record.created, self.timezone)
        else:
            dt = datetime.fromtimestamp(record.created)
        return dt.strftime(datefmt or self.default_time_format)


class GlobalFormatter(logging.Formatter):
    def __init__(self, *, fmt, settings: LoggerSettings, datefmt=None):
        self.settings = settings
        self.timezone = None
        if settings.time_zone:
            try:
                self.timezone = pytz.timezone(settings.time_zone)
                logging.info(
                    f"Console logger time zone set to: {self.timezone}")
            except pytz.UnknownTimeZoneError:
                logging.error(
                    f"Console logger: invalid time zone: {settings.time_zone}")
        logging.Formatter.__init__(self, fmt=fmt, datefmt=datefmt)

    def formatTime(self, record, datefmt=None):
        if self.timezone:
            dt = datetime.fromtimestamp(record.created, self.timezone)
        else:
            dt = datetime.fromtimestamp(record.created)
        return dt.strftime(datefmt or self.default_time_format)

    def format(self, record):
        record.emoji_is_present = (
            record.emoji_is_present if hasattr(
                record, "emoji_is_present") else False
        )
        if (
            hasattr(record, "emoji")
            and self.settings.emoji is True
            and record.emoji_is_present is False
        ):
            record.msg = emoji.emojize(
                f"{record.emoji}  {record.msg.strip()}", language="alias"
            )
            record.emoji_is_present = True

        if self.settings.emoji is False:
            if "\u2192" in record.msg:
                record.msg = record.msg.replace("\u2192", "-->")

            # With the update of Stream class, the Stream Title may contain emoji
            # Full remove using a method from utils.
            record.msg = remove_emoji(record.msg)

        record.msg = self.settings.username + record.msg

        if hasattr(record, "event"):
            self.telegram(record)
            self.discord(record)
            self.webhook(record)
            self.matrix(record)
            self.pushover(record)
            self.gotify(record)

            if self.settings.colored is True:
                record.msg = (
                    f"{self.settings.color_palette.get(record.event)}{record.msg}"
                )

        return super().format(record)

    def telegram(self, record):
        skip_telegram = False if hasattr(
            record, "skip_telegram") is False else True

        if (
            self.settings.telegram is not None
            and skip_telegram is False
            and self.settings.telegram.chat_id != 123456789
        ):
            self.settings.telegram.send(record.msg, record.event)

    def discord(self, record):
        skip_discord = False if hasattr(
            record, "skip_discord") is False else True

        if (
            self.settings.discord is not None
            and skip_discord is False
            and self.settings.discord.webhook_api
            != "https://discord.com/api/webhooks/0123456789/0a1B2c3D4e5F6g7H8i9J"
        ):
            self.settings.discord.send(record.msg, record.event)

    def webhook(self, record):
        skip_webhook = False if hasattr(
            record, "skip_webhook") is False else True

        if (
            self.settings.webhook is not None
            and skip_webhook is False
            and self.settings.webhook.endpoint
            != "https://example.com/webhook"
        ):
            self.settings.webhook.send(record.msg, record.event)

    def matrix(self, record):
        skip_matrix = False if hasattr(
            record, "skip_matrix") is False else True

        if (
            self.settings.matrix is not None
            and skip_matrix is False
            and self.settings.matrix.room_id != "..."
            and self.settings.matrix.access_token
        ):
            self.settings.matrix.send(record.msg, record.event)

    def pushover(self, record):
        skip_pushover = False if hasattr(
            record, "skip_pushover") is False else True

        if (
            self.settings.pushover is not None
            and skip_pushover is False
            and self.settings.pushover.userkey != "YOUR-ACCOUNT-TOKEN"
            and self.settings.pushover.token != "YOUR-APPLICATION-TOKEN"
        ):
            self.settings.pushover.send(record.msg, record.event)

    def gotify(self, record):
        skip_gotify = False if hasattr(
            record, "skip_gotify") is False else True

        if (
            self.settings.gotify is not None
            and skip_gotify is False
            and self.settings.gotify.endpoint
            != "https://example.com/message?token=TOKEN"
        ):
            self.settings.gotify.send(record.msg, record.event)


def configure_loggers(username, settings):
    if settings.colored is True:
        init(autoreset=True)

    # Queue handler that will handle the logger queue
    logger_queue = queue.Queue(-1)
    queue_handler = QueueHandler(logger_queue)
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    # Add the queue handler to the root logger
    # Send log messages to another thread through the queue
    root_logger.addHandler(queue_handler)

    # Adding a username to the format based on settings
    console_username = "" if settings.console_username is False else f"[{username}] "

    settings.username = console_username

    json_format = {
        "timestamp": "asctime",
        "exc_text": "exc_text",
        "filename": "filename",
        "funcName": "funcName",
        "level": "levelname",
        "lineno": "lineno",
        "module": "module",
        "msecs": "msecs",
        "message": "message",
        "name": "name",
        "pathname": "pathname",
        "process": "process",
        "processName": "processName",
        "relativeCreated": "relativeCreated",
        "stack_info": "stack_info",
        "thread": "thread",
        "threadName": "threadName",
    }

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(settings.console_level)
    formatter = None
    if settings.console_format == TEXT:
        formatter = GlobalFormatter(
            fmt=(
                "%(asctime)s - %(levelname)s - [%(funcName)s]: %(message)s"
                if settings.less is False
                else "%(asctime)s - %(message)s"
            ),
            datefmt=(
                "%d/%m/%y %H:%M:%S" if settings.less is False else "%d/%m %H:%M:%S"
            ),
            settings=settings,
        )
    elif settings.console_format == JSON:
        formatter = JsonFormatter(fmt_dict=json_format)
    else:
        raise ValueError("Invalid console format")

    console_handler.setFormatter(formatter)

    if settings.save is True:
        logs_path = os.path.join(Path().absolute(), "logs")
        Path(logs_path).mkdir(parents=True, exist_ok=True)
        if settings.auto_clear is True:
            logs_file = os.path.join(
                logs_path,
                f"{username}.log",
            )
            file_handler = TimedRotatingFileHandler(
                logs_file,
                when="D",
                interval=1,
                backupCount=7,
                encoding="utf-8",
                delay=False,
            )
        else:
            # Getting time zone from the console_handler's formatter since they are the same
            tz = "" if console_handler.formatter.timezone is False else console_handler.formatter.timezone
            logs_file = os.path.join(
                logs_path,
                f"{username}.{datetime.now(tz).strftime('%Y%m%d-%H%M%S')}.log",
            )
            file_handler = logging.FileHandler(logs_file, "w", "utf-8")

        file_formatter = None
        if settings.file_format == TEXT:
            file_formatter = FileFormatter(
                fmt="%(asctime)s - %(levelname)s - %(name)s - [%(funcName)s]: %(message)s",
                datefmt="%d/%m/%y %H:%M:%S",
                settings=settings
            )
        elif settings.file_format == JSON:
            file_formatter = JsonFormatter(fmt_dict=json_format)
        else:
            raise ValueError("Invalid file format")

        file_handler.setFormatter(file_formatter)
        file_handler.setLevel(settings.file_level)

        # Add logger handlers to the logger queue and start the process
        queue_listener = QueueListener(
            logger_queue, file_handler, console_handler, respect_handler_level=True
        )
        queue_listener.start()
        return logs_file, queue_listener
    else:
        queue_listener = QueueListener(
            logger_queue, console_handler, respect_handler_level=True
        )
        queue_listener.start()
        return None, queue_listener
