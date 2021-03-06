"""
:summary: Connection object for Rundeck client

:license: Creative Commons Attribution-ShareAlike 3.0 Unported
:author: Mark LaPerriere
:contact: rundeckrun@mindmind.com
:copyright: Mark LaPerriere 2013

:requires: requests
"""
__docformat__ = "restructuredtext en"

from functools import wraps
import xml.dom.minidom as xml_dom

import requests

from .transforms import ElementTree
from .defaults import RUNDECK_API_VERSION
from .exceptions import InvalidAuthentication, RundeckServerError


def memoize(obj):
    cache = obj.cache = {}

    @wraps(obj)
    def memoizer(*args, **kwargs):
        key = str(args) + str(kwargs)
        if key not in cache:
            cache[key] = obj(*args, **kwargs)
        return cache[key]
    return memoizer


class RundeckResponse(object):

    def __init__(self, response, as_dict_method=None):
        """ Parses an XML string into a convenient Python object

        :Parameters:
            response : requests.Response
                an instance of the requests.Response returned by the associated command request
        """
        self._as_dict_method = None
        self.response = response
        self.body = self.response.text
        self.etree = ElementTree.fromstring(self.body)

    @memoize
    def pprint(self):
        return xml_dom.parseString(self.body).toprettyxml()

    @property
    @memoize
    def as_dict(self):
        if self._as_dict_method is None:
            return None
        else:
            return self._as_dict_method(self)

    @property
    @memoize
    def api_version(self):
        return int(self.etree.attrib.get('apiversion', -1))

    @property
    @memoize
    def success(self):
        return 'success' in self.etree.attrib

    @property
    @memoize
    def message(self):
        if self.success:
            term = 'success'
        else:
            term = 'error'

        message_el = self.etree.find(term)

        if message_el is None:
            return term
        else:
            return message_el.find('message').text

    def raise_for_error(self, msg=None):
        if msg is None:
            msg = self.message

        if not self.success:
            raise RundeckServerError(msg, rundeck_response=self)


class RundeckConnectionTolerant(object):

    def __init__(self, server='localhost', protocol='http', port=4440, api_token=None, **kwargs):
        """ Initialize a Rundeck API client connection

        :Parameters:
            server : str
                hostname of the Rundeck server (default: localhost)
            protocol : str
                either http or https (default: 'http')
            port : int
                Rundeck server port (default: 4440)
            api_token : str
                *\*\*Preferred method of authentication* - valid Rundeck user API token
                (default: None)

        :Keywords:
            usr : str
                Rundeck user name (used in place of api_token)
            pwd : str
                Rundeck user password (used in combo with usr)
            api_version : int
                Rundeck API version
            verify_cert : bool
                Server certificate verification (HTTPS only)
        """
        self.protocol = protocol
        self.usr = usr = kwargs.get('usr', None)
        self.pwd = pwd = kwargs.get('pwd', None)
        self.server = server
        self.api_token = api_token
        self.api_version = kwargs.get('api_version', RUNDECK_API_VERSION)
        self.verify_cert = kwargs.get('verify_cert', True)

        if (protocol == 'http' and port != 80) or (protocol == 'https' and port != 443):
            self.server = '{0}:{1}'.format(server, port)

        if api_token is None and usr is None and pwd is None:
            raise InvalidAuthentication('Must supply either api_token or usr and pwd')

        self.http = requests.Session()
        self.http.verify = self.verify_cert
        if api_token is not None:
            self.http.headers['X-Rundeck-Auth-Token'] = api_token
        elif usr is not None and pwd is not None:
            # TODO: support username/password authentication (maybe)
            raise NotImplementedError('Username/password authentication is not yet supported')

        self.base_url = '{0}://{1}/api'.format(self.protocol, self.server)

    def make_url(self, api_url):
        """ Creates a valid Rundeck URL based on the API and the base url of
        the RundeckConnection

        :Parameters:
            api_url : str
                the Rundeck API URL

        :rtype: str
        :return: full Rundeck API URL
        """
        return '/'.join([self.base_url, str(self.api_version), api_url.lstrip('/')])

    def call(self, method, url, params=None, headers=None, data=None, files=None,
        parse_response=True, **kwargs):
        """ Format the URL in preparation for making the HTTP request and return a
        RundeckResponse if requested/necessary

        :Parameters:
            method : str
                the HTTP request method
            url : str
                API URL
            params : dict({str: str, ...})
                a dict of query string params (default: None)
            headers : dict({str: str, ...})
                a dict of HTTP headers
            data : str
                the XML or YAML payload necessary for some commands
                (default: None)
            files : dict({str: str, ...})
                a dict of files to upload
            parse_response : bool
                parse the response as an xml message

        :Keywords:
            **passed along to RundeckConnection.request**

        :rtype: requests.Response
        """
        url = self.make_url(url)
        auth_header = {'X-Rundeck-Auth-Token': self.api_token}
        if headers is None:
            headers = auth_header
        else:
            headers.update(auth_header)

        response = self.request(
            method, url, params=params, data=data, headers=headers, files=files, **kwargs)

        if parse_response:
            return RundeckResponse(response)
        else:
            return response

    def request(self, method, url, params=None, headers=None, data=None, files=None):
        """ Sends the HTTP request to Rundeck

        :Parameters:
            method : str
                the HTTP request method
            url : str
                API URL
            params : dict({str: str, ...})
                a dict of query string params (default: None)
            data : str
                the url encoded payload necessary for some commands (default: None)
            files : dict({str: str, ...})
                a dict of files to upload

        :rtype: requests.Response
        """
        return self.http.request(
            method, url, params=params, data=data, headers=headers, files=files)


class RundeckConnection(RundeckConnectionTolerant):

    def request(self, method, url, params=None, headers=None, data=None, files=None,
        quiet=False):
        """ Override to call raise_for_status forcing non-successful HTTP responses to bubble up as
        as exceptions

        :Parameters:
            method : str
                the HTTP request method
            url : str
                API URL
            params : dict({str: str, ...})
                a dict of query string params (default: None)
            data : str
                the url encoded payload necessary for some commands (default: None)
            files : dict({str: str, ...})
                a dict of files to upload (default: None)
            quiet : bool
                suppress calling raise_for_status (default: False)

        :rtype: requests.Response
        """
        response = super(RundeckConnection, self).request(
            method, url, params=params, data=data, headers=headers, files=files)

        if not quiet:
            response.raise_for_status()

        return response
