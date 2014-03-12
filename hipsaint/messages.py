import logging
import requests
import socket
import time
from os import path
from jinja2.loaders import FileSystemLoader
from jinja2 import Environment
from hipsaint.options import COLORS

logging.basicConfig()
log = logging.getLogger(__name__)


class HipchatMessage(object):
    url = "https://api.hipchat.com/v1/rooms/message"
    default_color = 'red'
    DEFAULT_MAX_CONNECTION_RETRIES = 3
    DEFAULT_RETRY_SLEEP = 3  # seconds
    HIPCHAT_MAX_BODY_LENGTH = 10000  # characters

    def __init__(self, type, inputs, token, user, room_id, notify, **kwargs):
        self.type = type
        self.inputs = inputs
        self.token = token
        self.user = user
        self.room_id = room_id
        self.notify = notify
        self.max_connection_retries = self.DEFAULT_MAX_CONNECTION_RETRIES
        self.retry_sleep = self.DEFAULT_RETRY_SLEEP

    def deliver_payload(self, **kwargs):
        """ Makes HTTP GET request to HipChat containing the message from nagios
            according to API Documentation https://www.hipchat.com/docs/api/method/rooms/message
        """
        message_body = self.render_message()
        if len(message_body) > self.HIPCHAT_MAX_BODY_LENGTH:
            # HipChat API will not accept this message; warn and truncate
            log.warning("Message beginning with '{0}' too long, will be truncated".format(message_body[0:25]))
            message_body = message_body[0:self.HIPCHAT_MAX_BODY_LENGTH]

        message = {'room_id': self.room_id,
                   'from': self.user,
                   'message': message_body,
                   'color': self.message_color,
                   'notify': int(self.notify),
                   'auth_token': self.token}
        message.update(kwargs)

        # Attempt to send message to HipChat API, retrying on exception
        current_retry = 1
        ex = None
        while current_retry <= self.max_connection_retries:
            try:
                raw_response = requests.get(self.url, params=message)
                response_data = raw_response.json()
                break
            except requests.exceptions.ConnectionError as ex:
                # usually an issue with HipChat API causing an exception,
                # typical error is <class 'httplib.BadStatusLine'>
                # warn and wait before retrying request
                log.warning('Failed to submit message to HipChat API '
                            '(retry {0}/{1})'.format(current_retry,
                                                     self.max_connection_retries))
                current_retry += 1
                raw_response = None
                response_data = {}
                time.sleep(self.retry_sleep)


        if 'error' in response_data:
            error_message = response_data['error'].get('message')
            error_type = response_data['error'].get('type')
            error_code = response_data['error'].get('code')
            log.error('%s - %s: %s', error_code, error_type, error_message)
        elif not 'status' in response_data:
            log.error('Unexpected response: possible exception {0}'.format(ex))
        return raw_response

    def render_message(self):
        """ Unpacks Nagios inputs and renders the appropriate template depending
            on the notification type.
        """
        template_type = self.type
        inputs = [x.strip() for x in self.inputs.split('|')]

        if template_type == 'host' or template_type == 'short-host':
            hostname, timestamp, ntype, hostaddress, state, hostoutput = inputs
        elif template_type == 'service' or template_type == 'short-service':
            servicedesc, hostalias, timestamp, ntype, hostaddress, state, serviceoutput = inputs
        else:
            raise Exception('Invalid notification type')

        if ntype != 'PROBLEM':
            self.message_color = COLORS.get(ntype, self.default_color)
        else:
            self.message_color = COLORS.get(state, self.default_color)
        nagios_host = socket.gethostname().split('.')[0]

        template_path = path.realpath(path.join(path.dirname(__file__), 'templates'))
        env = Environment(loader=FileSystemLoader(template_path))
        template = env.get_template('{tmpl}.html'.format(tmpl=template_type))
        context = locals()
        context.pop('self')
        return template.render(**context)
