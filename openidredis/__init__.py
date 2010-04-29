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
    def __init__(self, host='localhost', port=6379, db=0, key_prefix='oid_redis'):
        self.host = host
        self.port = port
        self.db = db
        self.key_prefix = key_prefix
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

        filename = '%s-%s-%s-%s-%s' % (self.key_prefix, proto, domain, url_hash, handle_hash)
        log.debug('Returning filename: %s', filename)
        return filename

    def storeAssociation(self, server_url, association):
        # Determine how long this association is good for
        issued_offset = int(time.time()) - association.issued
        seconds_from_now = issued_offset + association.lifetime
        
        # If this association is already expired, don't even store it
        if seconds_from_now < 1:
            return None
        
        association_s = association.serialize()
        key_name = self.getAssociationFilename(server_url, association.handle)
        
        self._conn.set(key_name, association_s)
        log.debug('Storing key: %s', key_name)
    
        # By default, set the expiration from the assocation expiration
        self._conn.expire(key_name, seconds_from_now)
        log.debug('Expiring: %s, in %s seconds', key_name, seconds_from_now)
        return None
    
    def getAssociation(self, server_url, handle=None):
        log.debug('Association requested for server_url: %s, with handle: %s', server_url, handle)
        if handle is None:
            # Retrieve all the keys for this server connection
            key_name = self.getAssociationFilename(server_url, '')
            assocs = self._conn.keys('%s*' % key_name)
            
            if not assocs:
                log.debug('No association found for: %s', server_url)
                return None
            
            # Now use the one that was issued most recently
            associations = []
            for assoc in self._conn.mget(assocs):
                associations.append(Association.deserialize(assoc))
            associations.sort(cmp=lambda x,y: cmp(x.issued, y.issued))
            log.debug('getAssociation found, returns most recently issued')
            return associations[-1]
        else:
            key_name = self.getAssociationFilename(server_url, handle)
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
            log.debug('Timestamp from current time is less than skew')
            return False
        
        # We're not even holding onto nonces apparently
        if nonce.SKEW < 1:
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

        anonce = '%s-nonce-%08x-%s-%s-%s-%s' % (self.key_prefix, timestamp, proto, domain,
                                         url_hash, salt_hash)
        exists = self._conn.getset(anonce, '%s' % timestamp)
        log.debug('And new_nonce results: %s', exists)
        if exists:
            log.debug('Nonce already exists, oops: %s', anonce)
            return False
        else:
            log.debug('Unused nonce, all good: %s', anonce)
            # Let's set an expire time
            curr_offset = time.time() - timestamp
            self._conn.expire(anonce, curr_offset + nonce.SKEW)
            return True
    
    def cleanupNonces(self):
        keys = self._conn.keys('%s-nonce-*' % self.key_prefix)
        expired = 0
        for key in keys:
            # See if its expired
            timestamp = int(self._conn.get(key))
            if abs(timestamp - time.time()) > nonce.SKEW:
                self._conn.delete(key)
                expired += 1
        return expired
