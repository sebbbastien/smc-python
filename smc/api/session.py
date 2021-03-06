"""
Session module for tracking existing connection state to SMC
"""
import json
import logging
import requests

import smc.api.web
from smc.api.entry_point import Resource
from smc.elements.user import ApiClient
from smc.api.exceptions import ConfigLoadError, SMCConnectionError
from smc.api.configloader import load_from_file, load_from_environ
# requests.packages.urllib3.disable_warnings()

logger = logging.getLogger(__name__)


'''
#from requests.adapters import HTTPAdapter
#from requests.packages.urllib3.poolmanager import PoolManager
class SSLAdapter(HTTPAdapter):
    """
    An HTTPS Transport Adapter that uses an arbitrary SSL version.
    Version should be a valid protocol from python ssl library.
    """
    def __init__(self, ssl_version=None, **kwargs):
        self.ssl_version = ssl_version

        super(SSLAdapter, self).__init__(**kwargs)

    def init_poolmanager(self, connections, maxsize, block=False):
        self.poolmanager = PoolManager(
            num_pools=connections,
            maxsize=maxsize,
            block=block,
            ssl_version=self.ssl_version)
'''

class Session(object):
    """
    Session represents the clients session to the SMC. As session is obtained
    by calling login(). If sessions need to be long lived as might be the case
    when running under a web platform, a session is automatically refreshed
    when it expires. Best practice is to call logout() after to clear the
    session from the SMC.
    """
    _MODS_LOADED = False
    
    #: The default format string to use when configuring the logger
    LOG_FORMAT = '%(asctime)s - %(name)s - [%(levelname)s] - %(message)s'
    
    def __init__(self):
        self._api_version = None
        self._session = None # Python requests session object
        self._connection = None # SMCAPIConnection
        self._url = None
        self._timeout = 10
        self._domain = 'Shared Domain'
        # Extra args are collected and used if provided. These are generally
        # not needed but may be needed to enable visibility of beta features
        self._extra_args = {}
        # Resource provides an interface to entry points
        self._resource = Resource()
        self.credential = Credential()
        # Added to support domain switching. Sessions store a dict of
        # {'domain': session} to allow for switching domains within a
        # single session
        self._sessions = {}
    
    @property
    def entry_points(self):
        if not len(self._resource):
            raise SMCConnectionError(
                "No entry points found, it is likely there is no valid "
                "login session.")
        return self._resource

    @property
    def api_version(self):
        """ API Version """
        return self._api_version

    @property
    def session(self):
        """ Session for this interpreter """
        return self._session

    @property
    def session_id(self):
        """ The session ID in header type format. Can be inserted
        into a connection if necessary using
        {'Cookie': session.session_id}
        """
        return 'JSESSIONID=%s' % self.session.cookies.get('JSESSIONID')\
            if self.session else None

    @property
    def connection(self):
        return self._connection

    @property
    def url(self):
        """ SMC URL """
        return self._url
    
    @property
    def web_socket_url(self):
        socket_proto = 'wss' if self.is_ssl else 'ws'    
        return '{}://{}/{}'.format(
            socket_proto, self.url.split('://')[-1], self.api_version)
    
    @property
    def is_ssl(self):
        return self.url.startswith('https') if self.session else False

    @property
    def timeout(self):
        """ Session timeout """
        return self._timeout

    @property
    def domain(self):
        """ Logged in domain """
        return self._domain

    @property
    def current_user(self):
        """
        .. versionadded:: 0.6.0
            Requires SMC version >= 6.4
        
        Return the currently logged on API Client user element.
        
        :raises UnsupportedEntryPoint: Current user is only supported with SMC
            version >= 6.4
        :rtype: ApiClient
        """
        if self.session:
            response = self.session.get(self.entry_points.get('current_user'))
            if response.status_code in (200, 201):
                return ApiClient.from_href(response.json().get('value'))
    
    def login(self, url=None, api_key=None, login=None, pwd=None, api_version=None,
              timeout=None, verify=True, alt_filepath=None, domain=None, **kwargs):
        """
        Login to SMC API and retrieve a valid session.
        Session will be re-used when multiple queries are required.

        An example login and logout session::

            from smc import session
            session.login(url='http://1.1.1.1:8082', api_key='SomeSMCG3ener@t3dPwd')
            .....do stuff.....
            session.logout()

        :param str url: ip of SMC management server
        :param str api_key: API key created for api client in SMC
        :param str login: Administrator user in SMC that has privilege to SMC API.
        :param str pwd: Password for user login.
        :param api_version (optional): specify api version
        :param int timeout: (optional): specify a timeout for initial connect; (default 10)
        :param str|boolean verify: verify SSL connections using cert (default: verify=True)
            You can pass verify the path to a CA_BUNDLE file or directory with certificates
            of trusted CAs
        :param str alt_filepath: If using .smcrc, alternate file+path
        :param str domain: domain to log in to. If domains are not configured, this
            field will be ignored and api client logged in to 'Shared Domain'.
        :param bool retry_on_busy: pass as kwarg with boolean if you want to add retries
            if the SMC returns HTTP 503 error during operation. You can also optionally customize
            this behavior and call :meth:`.set_retry_on_busy`
        :raises ConfigLoadError: loading cfg from ~.smcrc fails

        For SSL connections, you can disable validation of the SMC SSL certificate by setting
        verify=False, however this is not a recommended practice.

        If you want to use the SSL certificate generated and used by the SMC API server
        for validation, set verify='path_to_my_dot_pem'. It is also recommended that your
        certificate has subjectAltName defined per RFC 2818
        
        If SSL warnings are thrown in debug output, see:
        https://urllib3.readthedocs.io/en/latest/advanced-usage.html#ssl-warnings

        Logout should be called to remove the session immediately from the
        SMC server.
        
        .. note:: As of SMC 6.4 it is possible to give a standard Administrative user access
            to the SMC API. It is still possible to use an API Client by providing the api_key
            in the login call.
        """
        if not url or (not api_key and not (login and pwd)):
            # First try load from file
            try:
                cfg = load_from_file(alt_filepath) if alt_filepath\
                    is not None else load_from_file()
                logger.debug('Read config data from file: %s', cfg)
            except ConfigLoadError:
                # Last ditch effort, try to load from environment
                cfg = load_from_environ()
                logger.debug('Read config data from environ: %s', cfg)
                
            url = cfg.get('url')
            api_key = cfg.get('api_key')
            api_version = cfg.get('api_version')
            verify = cfg.get('verify')
            timeout = cfg.get('timeout')
            domain = cfg.get('domain')
            kwargs = cfg.get('kwargs', {})
        
        self._timeout = timeout or self._timeout
        self._domain = domain or self._domain
        self._url = url
        
        # Determine and set the API version we will use.
        self._api_version = get_api_version(url, api_version, timeout, verify)
        
        # Set the auth provider which will determine what type of login this is
        self.credential = Credential(api_key, login, pwd)
        
        # Retries configured generically
        retry_on_busy = kwargs.pop('retry_on_busy', False)
        
        request = self._build_auth_request(verify=verify, **kwargs)
        
        # This will raise if session login fails...
        self._session = self._get_session(request)
        self.session.verify = verify
        
        logger.debug('Login succeeded and session retrieved: %s, domain: %s',
            self.session_id, self.domain)
        
        if retry_on_busy:
            self.set_retry_on_busy()
        
        self._sessions[self.domain] = self.session
        if self.connection is None:
            self._connection = smc.api.web.SMCAPIConnection(self)
             
        # Load entry points
        load_entry_points(self)

        if not self._MODS_LOADED:
            logger.debug('Registering class mappings.')
            # Load the modules to register needed classes
            for pkg in ('smc.policy', 'smc.elements', 'smc.routing',
                        'smc.vpn', 'smc.administration', 'smc.core',
                        'smc.administration.user_auth'):
                import_submodules(pkg, recursive=False)

            self._MODS_LOADED = True
    
    def _build_auth_request(self, verify=False, **kwargs):
        """
        Build the authentication request to SMC
        """
        json = {
            'domain': self.domain
        }
        
        params = {}
        if self.credential.provider_name.startswith('lms'):
            params = self.credential.get_credentials()
        else:
            json.update(authenticationkey=self.credential._api_key)
        
        if kwargs:
            json.update(**kwargs)
            self._extra_args.update(**kwargs) # Store in case we need to rebuild later
        
        request = dict(
            url=self.credential.get_provider_entry_point(self.url, self.api_version),
            json=json,
            params=params,
            headers={'content-type': 'application/json'},
            verify=verify)
        
        return request
    
    def _get_session(self, request):
        """
        Authenticate the request dict
        
        :param dict request: request dict built from user input
        :raises SMCConnectionError: failure to connect
        :return: python requests session
        :rtype: requests.Session
        """
        _session = requests.session()  # empty session
        
        response = _session.post(**request)
        logger.info('Using SMC API version: %s', self.api_version)
        
        if response.status_code != 200:
            raise SMCConnectionError(
                'Login failed, HTTP status code: %s and reason: %s' % (
                    response.status_code, response.reason))
        return _session

    def logout(self):
        """ Logout session from SMC """
        if self._sessions:
            for domain, session in self._sessions.items():
                try:
                    r = session.put(self.entry_points.get('logout'))
                    if r.status_code == 204:
                        logger.info('Logged out of domain: %s successfully', domain)
                        logger.debug('Call counters: %s' % smc.api.web.counters)
                    else:
                        logger.error('Logout status was unexpected. Received response '
                                     'with status code: %s', (r.status_code))

                except requests.exceptions.SSLError as e:
                    logger.error('SSL exception thrown during logout: %s', e)
                except requests.exceptions.ConnectionError as e:
                    logger.error('Connection error on logout: %s', e)
            
            self.entry_points.clear()
            self._session = None

    def refresh(self):
        """
        Refresh session on 401. Wrap this in a loop with retries.

        :raises SMCConnectionError: Problem re-authenticating using existing
            api credentials
        """
        # Did we already have a session that just timed out
        if self.session and self.credential.has_credentials and self.url:
            # Try relogging in to refresh, otherwise fail
            logger.info('Session timed out, will try obtaining a new session using '
                'previously saved credential information.')
            self.login(**self._get_login_params())
            return
        raise SMCConnectionError('Session expired and attempted refresh failed.')        
    
    def switch_domain(self, domain):
        """
        Switch from one domain to another. You can call session.login() with a domain
        key value to log directly into the domain of choice or alternatively switch
        from domain to domain. The user must have permissions to the domain or
        unauthorized will be returned. 
        ::
        
            session.login() # Log in to 'Shared Domain'
            ...
            session.switch_domain('MyDomain')
        
        :raises SMCConnectionError: Error logging in to specified domain.
            This typically means the domain either doesn't exist or the
            user does not have privileges to that domain.
        """
        if self.domain != domain:
            # Do we already have a session
            if domain not in self._sessions:
                logger.info('Creating session for domain: %s', domain)
                credentials = self._get_login_params()
                credentials.update(domain=domain)
                self.login(**credentials)
            else:
                logger.info('Switching to existing domain session: %s', domain)
                self._session = self._sessions.get(domain)
                self._domain = domain

    def set_file_logger(self, path, log_level=logging.DEBUG, format_string=None, logger_name='smc'):
        """
        Convenience function to quickly configure any level of logging
        to a file.
    
        :param int log_level: A log level as specified in the `logging` module
        :param str format_string: Optional format string as specified in the 
            `logging` module
        :param str path: Path to the log file.  The file will be created
            if it doesn't already exist.
        """
        if format_string is None: 
            format_string = self.LOG_FORMAT
        
        log = logging.getLogger(logger_name)
        log.setLevel(log_level)

        # create file handler and set level
        ch = logging.FileHandler(path)
        ch.setLevel(log_level)
        # create formatter
        formatter = logging.Formatter(format_string)
        # add formatter to ch
        ch.setFormatter(formatter)
        # add ch to logger
        log.addHandler(ch)
    
    def set_retry_on_busy(self, total=5, backoff_factor=0.1, status_forcelist=None, **kwargs):
        """
        Mount a custom retry object on the current session that allows service level
        retries when the SMC might reply with a Service Unavailable (503) message.
        This can be possible in larger environments with higher database activity.
        You can all this on the existing session, or provide as a dict to the login
        constructor.
        
        :param int total: total retries
        :param float backoff_factor: when to retry
        :param list status_forcelist: list of HTTP error codes to retry on
        :param list method_whitelist: list of methods to apply retries for, GET, POST and
            PUT by default
        :return: None
        """
        if self.session:
            from requests.adapters import HTTPAdapter
            from requests.packages.urllib3.util.retry import Retry
    
            method_whitelist = kwargs.pop('method_whitelist', []) or ['GET', 'POST', 'PUT']
            status_forcelist = frozenset(status_forcelist) if status_forcelist else frozenset([503])
            retry = Retry(
                total=total,
                backoff_factor=backoff_factor,
                status_forcelist=status_forcelist,
                method_whitelist=method_whitelist)
            
            for proto_str in ('http://', 'https://'):
                self.session.mount(proto_str, HTTPAdapter(max_retries=retry))
            logger.debug('Mounting retry object to HTTP session: %s' % retry) 
        
    def set_stream_logger(self, log_level=logging.DEBUG, format_string=None, logger_name='smc'): 
        """ 
        Stream logger convenience function to log to console
        
        :param int log_level: A log level as specified in the `logging` module
        :param str format_string: Optional format string as specified in the 
            `logging` module
        """ 
        if format_string is None: 
            format_string = self.LOG_FORMAT
     
        logger = logging.getLogger(logger_name) 
        logger.setLevel(log_level)
        
        # create console handler and set level
        ch = logging.StreamHandler() 
        ch.setLevel(log_level)
        # create formatter
        formatter = logging.Formatter(format_string)
        # add formatter to ch
        ch.setFormatter(formatter) 
        logger.addHandler(ch) 
    
    def _get_login_params(self):
        """
        Spec for login parameters
        """
        credentials = dict(
            url=self.url,
            api_version=self.api_version,
            timeout=self.timeout,
            verify=self._session.verify,
            domain=self.domain)
        credentials.update(self.credential.get_credentials())
        credentials.update(**self._extra_args)
        return credentials
    
    def _get_log_schema(self):
        """
        Get the log schema for this SMC version.
        
        :return: dict
        """
        if self.session and self.session_id:
            schema = '{}/{}/monitoring/log/schemas'.format(self.url, self.api_version)
            
            response = self.session.get(
                url=schema,
                headers={'cookie': self.session_id,
                         'content-type': 'application/json'})

            if response.status_code in (200, 201):
                return response.json()
                

class Credential(object):
    """
    Provider for authenticating the user. LMS Login is a user created within
    the SMC as a normal administrative account. Login is the standard way of
    using an API client and key as password.
    The key of the CredentialMap also indicates the entry point for which to
    POST the authentication.
    """
    CredentialMap = {
        'lms_login': ('login', 'pwd'),
        'login': ('api_key',)
    }
    
    def __init__(self, api_key=None, login=None, pwd=None):
        self._api_key = api_key
        self._login = login
        self._pwd = pwd

    @property
    def provider_name(self):
        if self._api_key:
            return 'login'
        return 'lms_login'
    
    def get_provider_entry_point(self, url, api_version):
        return '{url}/{api_version}/{provider_name}'.format(
            url=url, api_version=api_version, provider_name=self.provider_name)
    
    @property
    def has_credentials(self):
        """
        Does this session have valid credentials
        
        :rtype: bool
        """
        if self._api_key is not None:
            return True
        elif self._login is not None and self._pwd is not None:
            return True
        return False
    
    def get_credentials(self):
        """
        Return credentials as a dict
        
        :rtype: dict
        """
        if self.has_credentials:
            if self._api_key:
                return dict(
                    api_key=self._api_key)
            else:
                return dict(
                    login=self._login,
                    pwd=self._pwd)
        return {}


def load_entry_points(session):
    try:
        r = session.session.get('{url}/{api_version}/api'.format(
                url=session.url, api_version=session.api_version))
        
        if r.status_code == 200:
            result_list = json.loads(r.text)
            
            if session._resource:
                session.entry_points.clear()
            
            session._resource.add(result_list['entry_point'])
            logger.debug("Loaded entry points with obtained session.")
        
        else:
            raise SMCConnectionError(
                'Invalid status received while getting entry points from SMC. '
                'Status code received %s. Reason: %s' % (r.status_code, r.reason))
    
    except requests.exceptions.RequestException as e:
        raise SMCConnectionError(e)


def available_api_versions(base_url, timeout=10, verify=True):
    """
    Get all available API versions for this SMC

    :return version numbers
    :rtype: list
    """
    try:
        r = requests.get('%s/api' % base_url, timeout=timeout,
                         verify=verify)  # no session required
        
        if r.status_code == 200:
            j = json.loads(r.text)
            versions = []
            for version in j['version']:
                versions.append(version['rel'])
            return versions
        
        raise SMCConnectionError(
            'Invalid status received while getting entry points from SMC. '
            'Status code received %s. Reason: %s' % (r.status_code, r.reason))

    except requests.exceptions.RequestException as e:
        raise SMCConnectionError(e)


def get_api_version(base_url, api_version=None, timeout=10, verify=True):
    """
    Get the API version specified or resolve the latest version

    :return api version
    :rtype: float
    """
    versions = available_api_versions(base_url, timeout, verify)
    
    newest_version = max([float(i) for i in versions])
    if api_version is None:  # Use latest
        api_version = newest_version
    else:
        if api_version not in versions:
            api_version = newest_version
    
    return api_version


def import_submodules(package, recursive=True):
    """
    Import all submodules of a module, recursively,
    including subpackages.

    From http://stackoverflow.com/questions/3365740/how-to-import-all-submodules

    :param package: package (name or actual module)
    :type package: str | module
    :rtype: dict[str, types.ModuleType]
    """
    import importlib
    import pkgutil
    if isinstance(package, str):
        package = importlib.import_module(package)
    results = {}
    for _loader, name, is_pkg in pkgutil.walk_packages(package.__path__):
        full_name = package.__name__ + '.' + name
        results[full_name] = importlib.import_module(full_name)
        if recursive and is_pkg:
            results.update(import_submodules(full_name))
