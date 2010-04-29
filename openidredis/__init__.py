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
        self.log_debug = logging.DEBUG >= log.getEffectiveLevel()
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
        if self.log_debug:
            log.debug('Returning filename: %s', filename)
        return filename

    def storeAssociation(self, server_url, association):
        # Determine how long this association is good for
        issued_offset = int(time.time()) - association.issued
        seconds_from_now = issued_offset + association.lifetime
                
        association_s = association.serialize()
        key_name = self.getAssociationFilename(server_url, association.handle)
        
        self._conn.set(key_name, association_s)
        if self.log_debug:
            log.debug('Storing key: %s', key_name)
    
        # By default, set the expiration from the assocation expiration
        self._conn.expire(key_name, seconds_from_now)
        if self.log_debug:
            log.debug('Expiring: %s, in %s seconds', key_name, seconds_from_now)
        return None
    
    def getAssociation(self, server_url, handle=None):
        log_debug = self.log_debug
        
        if log_debug:
            log.debug('Association requested for server_url: %s, with handle: %s', server_url, handle)
        
        if handle is None:
            # Retrieve all the keys for this server connection
            key_name = self.getAssociationFilename(server_url, '')
            assocs = self._conn.keys('%s*' % key_name)
            
            if not assocs:
                if log_debug:
                    log.debug('No association found for: %s', server_url)
                return None
            
            # Now use the one that was issued most recently
            associations = []
            for assoc in self._conn.mget(assocs):
                associations.append(Association.deserialize(assoc))
            associations.sort(cmp=lambda x,y: cmp(x.issued, y.issued))
            if log_debug:
                log.debug('getAssociation found, returns most recently issued')
            return associations[-1]
        else:
            key_name = self.getAssociationFilename(server_url, handle)
            association_s = self._conn.get(key_name)
            if association_s:
                if log_debug:
                    log.debug('getAssociation found, returning association')
                return Association.deserialize(association_s)
            else:
                if log_debug:
                    log.debug('No association found for getAssociation')
                return None
    
    def removeAssociation(self, server_url, handle):
        key_name = self.getAssociationFilename(server_url, handle)
        if self.log_debug:
            log.debug('Removing association: %s', key_name)
        return self._conn.delete(key_name)
    
    def useNonce(self, server_url, timestamp, salt):
        log_debug = self.log_debug
        if abs(timestamp - time.time()) > nonce.SKEW:
            if log_debug:
                log.debug('Timestamp from current time is less than skew')
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
        if exists:
            if log_debug:
                log.debug('Nonce already exists: %s', anonce)
            return False
        else:
            if log_debug:
                log.debug('Unused nonce, storing: %s', anonce)
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
