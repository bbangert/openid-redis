"""Redis Store

This back-end is heavily based on the FileStore from the python-openid package
and sections are copied whole-sale from it.

python-openid FileStore code is Copyright JanRain, under the Apache Software
License.

"""
import logging
import string
import time

from openid import cryptutil
from openid import oidutil
from openid.association import Association
from openid.store import nonce
from openid.store.interface import OpenIDStore

import redis

__all__ = ['RedisStore']

_filename_allowed = string.ascii_letters + string.digits + '.'
_isFilenameSafe = set(_filename_allowed).__contains__

log = logging.getLogger(__name__)

def _safe64(s):
    h64 = oidutil.toBase64(cryptutil.sha1(s))
    h64 = h64.replace('+', '_')
    h64 = h64.replace('/', '.')
    h64 = h64.replace('=', '')
    return h64

def _filenameEscape(s):
    filename_chunks = []
    for c in s:
        if _isFilenameSafe(c):
            filename_chunks.append(c)
        else:
            filename_chunks.append('_%02X' % ord(c))
    return ''.join(filename_chunks)


class RedisStore(OpenIDStore):
    """Implementation of OpenIDStore for Redis"""
    def __init__(self, host='localhost', port=6379, db=0):
        self.host = host
        self.port = port
        self.db = db
        self._conn = redis.Redis(host=self.host, port=self.port, db=self.db)
    
    def getAssociationFilename(self, server_url, handle):
        """Create a unique filename for a given server url and
        handle. This implementation does not assume anything about the
        format of the handle. The filename that is returned will
        contain the domain name from the server URL for ease of human
        inspection of the data directory.

        (str, str) -> str
        """
        if server_url.find('://') == -1:
            raise ValueError('Bad server URL: %r' % server_url)

        proto, rest = server_url.split('://', 1)
        domain = _filenameEscape(rest.split('/', 1)[0])
        url_hash = _safe64(server_url)
        if handle:
            handle_hash = _safe64(handle)
        else:
            handle_hash = ''

        filename = '%s-%s-%s-%s' % (proto, domain, url_hash, handle_hash)
        log.debug('Returning filename: %s', filename)
        return filename

    def storeAssociation(self, server_url, association):
        association_s = association.serialize()
        full_key_name = self.getAssociationFilename(server_url, association.handle)
        server_key_name = self.getAssociationFilename(server_url, None)
        
        for key_name in [full_key_name, server_key_name]:
            self._conn.set(key_name, association_s)
            log.debug('Storing key: %s', key_name)
        
            # By default, set the expiration from the assocation expiration
            self._conn.expire(key_name, association.lifetime)
            log.debug('Expiring: %s, in %s seconds', key_name, association.lifetime)
        return None
    
    def getAssociation(self, server_url, handle=None):
        log.debug('Association requested for server_url: %s, with handle: %s', server_url, handle)
        key_name = self.getAssociationFilename(server_url, handle)
        if handle is None:
            handle = ''
        association_s = self._conn.get(key_name)
        if association_s:
            log.debug('getAssociation found, returning association')
            return Association.deserialize(association_s)
        else:
            log.debug('No association found for getAssociation')
            return None
    
    def removeAssociation(self, server_url, handle):
        key_name = self.getAssociationFilename(server_url, handle)
        log.debug('Removing association: %s', key_name)
        return self._conn.delete(key_name)
    
    def useNonce(self, server_url, timestamp, salt):
        if abs(timestamp - time.time()) > nonce.SKEW:
            log.debug('Invalid nonce used, time skew boom')
            return False
        
        if server_url:
            proto, rest = server_url.split('://', 1)
        else:
            # Create empty proto / rest values for empty server_url,
            # which is part of a consumer-generated nonce.
            proto, rest = '', ''

        domain = _filenameEscape(rest.split('/', 1)[0])
        url_hash = _safe64(server_url)
        salt_hash = _safe64(salt)

        anonce = '%08x-%s-%s-%s-%s' % (timestamp, proto, domain,
                                         url_hash, salt_hash)
        new_nonce = self._conn.setnx(anonce, 'nonce')
        if new_nonce:
            # Expire the nonce in 5 minutes
            self._conn.expire(anonce, 300)
            log.debug('Unused nonce, all good')
            return True
        else:
            log.debug('Nonce already exists, oops')
            return False
