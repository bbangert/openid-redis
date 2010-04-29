"""Redis Store

This back-end is heavily based on the FileStore from the python-openid package
and sections are copied whole-sale from it.

python-openid FileStore code is Copyright JanRain, under the Apache Software
License.

"""
import string

from openid import cryptutil
from openid import oidutil
from openid.association import Association
from openid.store import nonce
from openid.store.interface import OpenIDStore

import redis

__all__ = ['RedisStore']

_filename_allowed = string.ascii_letters + string.digits + '.'
_isFilenameSafe = set(_filename_allowed).__contains__

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
        return filename

    def storeAssociation(self, server_url, association):
        """We use a bunch of the"""
        association_s = association.serialize()
        key_name = self.getAssociationFilename(server_url, association.handle)
        self._conn.set(key_name, association_s)
        
        # By default, set the expiration from the assocation expiration
        self._conn.expire(key_name, association.lifetime)
    
    def getAssociation(self, server_url, handle=None):
        key_name = self.getAssociationFilename(server_url, handle)
        if handle is None:
            handle = ''
        association_s = self._conn.get(key_name)
        if association_s:
            return Association.deserialize(association_s)
        else:
            return None
    
    def removeAssociation(self, server_url, handle):
        key_name = self.getAssociationFilename(server_url, handle)
        return self._conn.delete(key_name)
    
    def useNonce(self, server_url, timestamp, salt):
        if abs(timestamp - time.time()) > nonce.SKEW:
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
        exists = self._conn.setnx(anonce, 'nonce')
        if exists:
            return False
        else:
            # Expire the nonce in 5 minutes
            self._conn.expire(anonce, 300)
            return True
