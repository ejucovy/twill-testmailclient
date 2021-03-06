"""
Extensions for mail functions -- both testing sending mail
to a server, and testing mail that is sent by a server.

These extensions are pretty specific to my immediate need,
which is writing tests for Listen.

The extensions assume that the server is using 
 http://github.com/ejucovy/Products.TestMailHost/
which writes out mails to files instead of sending them,
and injects headers into the request to tell the client
where to find the mails.  The expected setup for these tests
has the client and server on the same physical machine,
so that the client can simply read the mail files written
by the server.
"""

from twill.namespaces import get_twill_glocals
from twill.errors import TwillAssertionError, TwillException
from twill.commands import get_browser
from twill.commands import go

def clear_mail():
    browser = get_browser()
    browser.clear_cookies(name='debug-mail-location')

def get_mail():
    browser = get_browser()
    mails = None
    for cookie in browser.cj:
        if cookie.name != 'debug-mail-location': 
            continue
        mails = cookie.value
        if mails.startswith('"'):
            mails = mails.strip('"')
        break
    if mails is None:
        mails = []
    else:
        mails = mails.split(';')
    return mails

def num_mails(num):
    num = int(num)
    if num != len(get_mail()):
        raise TwillAssertionError("Expected %s mails; we have %s" % 
                                  (num, len(get_mail())))


from pprint import pformat
import email
def select_mail_from_header(header, value):
    actuals = []
    _, locals = get_twill_glocals()
    for mailpath in get_mail():
        fp = open(mailpath)
        msg = email.message_from_file(fp)
        fp.close()
        actual = msg.get(header)
        if value == actual:
            locals['__current_mail__'] = mailpath
            return
        actuals.append(actual)
    raise TwillAssertionError("No mail with header %s=%s was sent. Values were:\n%s" % (header, value, pformat(actuals)))

def print_selected_mail():
    mail = selected_mail()
    fp = open(mail)
    print fp.read()
    fp.close()

def selected_mail():
    globals, locals = get_twill_glocals()
    mail = locals.get('__current_mail__')
    if mail is None:
        raise TwillException("No mail is currently selected.")
    return mail

def unselect_mail():
    globals, locals = get_twill_glocals()
    mail = locals.get('__current_mail__')
    if mail is None:
        raise TwillException("No mail is currently selected.")
    del locals['__current_mail__']

def mail_has_header(header, value):
    mail = selected_mail()
    fp = open(mail)
    msg = email.message_from_file(fp)
    fp.close()
    actual = msg.get(header)
    if actual != value:
        raise TwillAssertionError("In mail %s, expected header %s=%s; got %s" % (
                mail, header, value, actual))

def mail_contains(value):
    mail = selected_mail()
    fp = open(mail)
    msg = email.message_from_file(fp)
    fp.close()
    body = msg.get_payload()
    if value not in body:
        raise TwillAssertionError("no match for <%s> in mail at %s" % (
                value, mail))

def click_link_in_mail(num=1):
    if num < 1:
        raise TwillException("You must use a positive index "
                             "for the link you wish to click")
    mail = selected_mail()
    fp = open(mail)
    text = fp.read()
    fp.close()
    text = text.split()
    links = [word for word in text if word.startswith("http://")]
    if len(links) < 0:
        raise TwillAssertionError(
            "Only %s links found in mail %s, "
            "so we can't click link #%s" % (
                len(links), mail, num))
    return go(link)

def send_mail(file, receiverURL):
    fp = open(file)
    mailStr = fp.read()
    fp.close()

    mails = send(receiverURL, mailStr)
    if mails is None: 
        return
    from twill.browser import mechanize
    cookie = mechanize.Cookie(None,
                              'debug-mail-location',
                              mails,
                              None, False,
                              '', False, False,
                              '/', False,
                              None, None, 
                              None, None, None, None, None)
    browser = get_browser()
    browser.cj.set_cookie(cookie)

"""
 smtp2zope.py - Read a email from stdin and forward it to a url

 Usage: smtp2zope.py URL [maxBytes]

 URL      = call this URL with the email as a post-request
                Authentication can be included:
                http://username:password@yourHost/...
                
 maxBytes = optional: only forward mails < maxBytes to URL

 Please note: Output is logged to maillog per default on unices.
 See your maillog to debug problems with the setup.

 This program is free software; you can redistribute it and/or
 modify it under the terms of the GNU General Public License
 as published by the Free Software Foundation; either version 2
 of the License, or (at your option) any later version.

 This program is distributed in the hope that it will be useful,
 but WITHOUT ANY WARRANTY; without even the implied warranty of
 MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 GNU General Public License for more details.

 You should have received a copy of the GNU General Public License
 along with this program; if not, write to the Free Software
 Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.
"""

import os
import sys
import urllib
import urllib2
import base64
import socket
import time
import errno
import random
import tempfile
from stat import ST_NLINK, ST_MTIME

##
# Portable, NFS-safe file locking with timeouts.
#
# This code has taken from the GNU MailMan mailing list system, 
# with our thanks. Code was modified by Maik Jablonski.
#

try:
    True, False
except NameError:
    True = 1
    False = 0

try:
    import MailBoxerTools, xmlrpclib
except:
    STRIP_ATTACHMENTS = 0
    
# Number of seconds the process expects to hold the lock
DEFAULT_LOCK_LIFETIME  = 30 #seconds

# Exceptions that can be raised by this module
class LockError(Exception):
    """Base class for all exceptions in this module."""

class AlreadyLockedError(LockError):
    """An attempt is made to lock an already locked object."""

class NotLockedError(LockError):
    """An attempt is made to unlock an object that isn't locked."""

class TimeOutError(LockError):
    """The timeout interval elapsed before the lock succeeded."""

class LockFile:
    """A portable way to lock resources by way of the file system. """

    COUNTER = 0

    def __init__(self, lockfile, lifetime=DEFAULT_LOCK_LIFETIME):
        """Create the resource lock using lockfile as the global lock file.

        Each process laying claim to this resource lock will create their own
        temporary lock files based on the path specified by lockfile.
        Optional lifetime is the number of seconds the process expects to hold
        the lock.  (see the module docstring for details).

        """
        self.__lockfile = lockfile
        self.__lifetime = lifetime
        # This works because we know we're single threaded
        self.__counter = LockFile.COUNTER
        LockFile.COUNTER += 1
        self.__tmpfname = '%s.%s.%d.%d' % (lockfile, 
                                           socket.gethostname(),
                                           os.getpid(),
                                           self.__counter)

    def set_lifetime(self, lifetime):
        """Set a new lock lifetime.

        This takes affect the next time the file is locked, but does not
        refresh a locked file.
        """
        self.__lifetime = lifetime

    def get_lifetime(self):
        """Return the lock's lifetime."""
        return self.__lifetime

    def refresh(self, newlifetime=None, unconditionally=False):
        """Refreshes the lifetime of a locked file.

        Use this if you realize that you need to keep a resource locked longer
        than you thought.  With optional newlifetime, set the lock's lifetime.
        Raises NotLockedError if the lock is not set, unless optional
        unconditionally flag is set to true.
        """
        if newlifetime is not None:
            self.set_lifetime(newlifetime)
        # Do we have the lock?  As a side effect, this refreshes the lock!
        if not self.locked() and not unconditionally:
            raise NotLockedError, '%s: %s' % (repr(self), self.__read())

    def lock(self, timeout=0):
        """Acquire the lock.

        This blocks until the lock is acquired unless optional timeout is
        greater than 0, in which case, a TimeOutError is raised when timeout
        number of seconds (or possibly more) expires without lock acquisition.
        Raises AlreadyLockedError if the lock is already set.
        """
        if timeout:
            timeout_time = time.time() + timeout
        # Make sure my temp lockfile exists, and that its contents are
        # up-to-date (e.g. the temp file name, and the lock lifetime).
        self.__write()
        # TBD: This next call can fail with an EPERM.  I have no idea why, but
        # I'm nervous about wrapping this in a try/except.  It seems to be a
        # very rare occurence, only happens from cron, and (only?) on Solaris
        # 2.6.
        self.__touch()

        while True:
            # Create the hard link and test for exactly 2 links to the file
            try:
                os.link(self.__tmpfname, self.__lockfile)
                # If we got here, we know we know we got the lock, and never
                # had it before, so we're done.  Just touch it again for the
                # fun of it.
                self.__touch()
                break
            except OSError, e:
                # The link failed for some reason, possibly because someone
                # else already has the lock (i.e. we got an EEXIST), or for
                # some other bizarre reason.
                if e.errno == errno.ENOENT:
                    # TBD: in some Linux environments, it is possible to get
                    # an ENOENT, which is truly strange, because this means
                    # that self.__tmpfname doesn't exist at the time of the
                    # os.link(), but self.__write() is supposed to guarantee
                    # that this happens!  I don't honestly know why this
                    # happens, but for now we just say we didn't acquire the
                    # lock, and try again next time.
                    pass
                elif e.errno <> errno.EEXIST:
                    # Something very bizarre happened.  Clean up our state and
                    # pass the error on up.
                    os.unlink(self.__tmpfname)
                    raise
                elif self.__linkcount() <> 2:
                    # Somebody's messin' with us!
                    pass
                elif self.__read() == self.__tmpfname:
                    # It was us that already had the link.
                    raise AlreadyLockedError
                # otherwise, someone else has the lock
                pass
            # We did not acquire the lock, because someone else already has
            # it.  Have we timed out in our quest for the lock?
            if timeout and timeout_time < time.time():
                os.unlink(self.__tmpfname)
                raise TimeOutError
            # Okay, we haven't timed out, but we didn't get the lock.  Let's
            # find if the lock lifetime has expired.
            if time.time() > self.__releasetime():
                # Yes, so break the lock.
                self.__break()
            # Okay, someone else has the lock, our claim hasn't timed out yet,
            # and the expected lock lifetime hasn't expired yet.  So let's
            # wait a while for the owner of the lock to give it up.
            self.__sleep()

    def unlock(self, unconditionally=False):
        """Unlock the lock.

        If we don't already own the lock (either because of unbalanced unlock
        calls, or because the lock was stolen out from under us), raise a
        NotLockedError, unless optional `unconditionally' is true.
        """
        islocked = self.locked()
        if not islocked and not unconditionally:
            raise NotLockedError
        # If we owned the lock, remove the global file, relinquishing it.
        if islocked:
            try:
                os.unlink(self.__lockfile)
            except OSError, e:
                if e.errno <> errno.ENOENT: raise
        # Remove our tempfile
        try:
            os.unlink(self.__tmpfname)
        except OSError, e:
            if e.errno <> errno.ENOENT: raise

    def locked(self):
        """Return true if we own the lock, false if we do not.

        Checking the status of the lock resets the lock's lifetime, which
        helps avoid race conditions during the lock status test.
        """
        # Discourage breaking the lock for a while.
        try:
            self.__touch()
        except OSError, e:
            if e.errno == errno.EPERM:
                # We can't touch the file because we're not the owner.  I
                # don't see how we can own the lock if we're not the owner.
                return False
            else:
                raise
        # TBD: can the link count ever be > 2?
        if self.__linkcount() <> 2:
            return False
        return self.__read() == self.__tmpfname

    def finalize(self):
        self.unlock(unconditionally=True)

    def __del__(self):
        self.finalize()

    #
    # Private interface
    #

    def __write(self):
        # Make sure it's group writable
        oldmask = os.umask(002)
        try:
            fp = open(self.__tmpfname, 'w')
            fp.write(self.__tmpfname)
            fp.close()
        finally:
            os.umask(oldmask)

    def __read(self):
        try:
            fp = open(self.__lockfile)
            filename = fp.read()
            fp.close()
            return filename
        except EnvironmentError, e:
            if e.errno <> errno.ENOENT: raise
            return None

    def __touch(self, filename=None):
        t = time.time() + self.__lifetime
        try:
            # TBD: We probably don't need to modify atime, but this is easier.
            os.utime(filename or self.__tmpfname, (t, t))
        except OSError, e:
            if e.errno <> errno.ENOENT: raise

    def __releasetime(self):
        try:
            return os.stat(self.__lockfile)[ST_MTIME]
        except OSError, e:
            if e.errno <> errno.ENOENT: raise
            return -1

    def __linkcount(self):
        try:
            return os.stat(self.__lockfile)[ST_NLINK]
        except OSError, e:
            if e.errno <> errno.ENOENT: raise
            return -1

    def __break(self):
        try:
            self.__touch(self.__lockfile)
        except OSError, e:
            if e.errno <> errno.EPERM: raise
        # Get the name of the old winner's temp file.
        winner = self.__read()
        # Remove the global lockfile, which actually breaks the lock.
        try:
            os.unlink(self.__lockfile)
        except OSError, e:
            if e.errno <> errno.ENOENT: raise
        # Try to remove the old winner's temp file, since we're assuming the
        # winner process has hung or died.
        try:
            if winner:
                os.unlink(winner)
        except OSError, e:
            if e.errno <> errno.ENOENT: raise

    def __sleep(self):
        interval = random.random() * 2.0 + 0.01
        time.sleep(interval)

def eventNotification(url, event_codes, mailString):
    event_codes = tuple(event_codes)
    if EVENT_NOTIFICATION and event_codes:
        server = xmlrpclib.ServerProxy(url)
        headers, body = MailBoxerTools.splitMail(mailString)
        server.manage_event(event_codes, headers)
    
##
# Main part of submitting an email to a http-server.
# All requests will be serialized with locks.

try:
    import syslog
    syslog.openlog('mailboxer')
    log_critical = lambda msg: syslog.syslog(syslog.LOG_CRIT|syslog.LOG_MAIL, msg)
    log_error = lambda msg: syslog.syslog(syslog.LOG_ERR|syslog.LOG_MAIL, msg)
    log_warning = lambda msg: syslog.syslog(syslog.LOG_WARNING|syslog.LOG_MAIL, msg)
    log_info = lambda msg: syslog.syslog(syslog.LOG_INFO|syslog.LOG_MAIL, msg)
except:
    # if we can't open syslog, just fake it
    fake_logger = lambda msg: sys.stderr.write(msg+"\n")
    log_critical = fake_logger
    log_error = fake_logger
    log_warning = fake_logger
    log_info = fake_logger

class BrokenHTTPRedirectHandler(urllib2.HTTPRedirectHandler):
    def http_error_302(self, req, fp, code, msg, headers):
        raise urllib2.HTTPError(req.get_full_url(), code, msg, headers, fp)

def send(callURL, mailString, maxBytes=None):


    # If you wish to use HTTP Basic Authentication, set a user id and password here.
    # Alternatively you can call the URL like:
    # http://username:password@yourHost/MailBoxer/manage_mailboxer
    # Note that this is not necessary in the default MailBoxer configuration, but
    # may be used to add some extra security.
    # Format: username:password
    AUTHORIZATION=''
    
    # If you want to strip out all attachments, leaving only plain text, set this.
    # If you have a email size limit set, it will apply on what is left _after_
    # attachment stripping. This will also trigger an 'error' message to be
    # (optionally) generated by MailBoxer, which provides an opportunity to
    # notify the sender of the attachment being stripped.
    #
    # If attachments are to be stripped, MailBoxerTools.py must also be available
    # in your PYTHONPATH. If MailBoxerTools.py is not available, this will be set
    # back to 0.
    STRIP_ATTACHMENTS = 0
    
    # Notify Zope-side MailBoxer of events (such as attachments that have been
    # stripped). Messages will still be logged to the syslog (if available).
    EVENT_NOTIFICATION = 0
    
    # If you have a special setup which don't allow locking / serialization,
    # set USE_LOCKS = 0
    USE_LOCKS = 1
    
    # This should work with Unix & Windows & MacOS,
    # if not, set it on your own (e.g. '/tmp/smtp2zope.lock').
    
    LOCKFILE_LOCATION = os.path.join(os.path.split(tempfile.mktemp())[0],
                                     'smtp2zope.lock')
    
    # The amount of time to wait to be serialised
    LOCK_TIMEOUT = 15 #seconds
        
    # Meaningful exit-codes for a smtp-server
    EXIT_USAGE = 64
    EXIT_NOUSER = 67
    EXIT_NOPERM = 77
    EXIT_TEMPFAIL = 75


    if callURL.find('http://') == -1:
        raise Exception('URL is specified (%s) is not a valid URL' % callURL)

    urlParts = urllib2.urlparse.urlparse(callURL)
    urlPath = '/'.join(filter(None, list(urlParts)[2].split('/'))[:-1])
    baseURL = urllib2.urlparse.urlunparse(urlParts[:2]+(urlPath,)+urlParts[3:])+'/'

    # Check for authentication-string (username:passwd) in URL
    # Url looks like: http://username:passwd@host/...
    auth_mark = callURL.find('@')
    if auth_mark<>-1:
        AUTHORIZATION = callURL[7:auth_mark]
        callURL = callURL.replace(AUTHORIZATION+'@','')

    # Check for optional maxBytes
    if maxBytes is not None:
        try:
            maxBytes  = long(maxBytes)
        except ValueError:
            raise Exception('the specified value of maxBytes (%s) was not an integer'
                            % maxBytes)
    else:
        maxBytes  = 0 # means: unlimited!!!

    if USE_LOCKS:
        # Create temporary lockfile
        lock = LockFile(LOCKFILE_LOCATION)
        try:
            lock.lock(LOCK_TIMEOUT)
        except TimeOutError:
            raise Exception('Serialisation timeout occurred, will request message to be requeued')

    event_codes = []
    if STRIP_ATTACHMENTS:
        # check to see if we have attachments
        text_body, content_type, html_body, attachments = MailBoxerTools.unpackMail(mailString)
        
        num_attachments = len(attachments)
        if num_attachments or html_body:
            content_type, text_body = MailBoxerTools.getPlainBodyFromMail(mailString)
            headers = MailBoxerTools.headersAsString(mailString, {'Content-Type': content_type})
            mailString = '%s\r\n\r\n%s' % (headers, text_body)
        
            if html_body:
                event_codes.append(100) # stripped HTML
                if num_attachments > 1: # we had a HTML _and_ attachments
                    event_codes.append(101) # stripped attachments
            elif num_attachments:
                event_codes.append(101) # stripped attachments
            
    # Check its size
    mailLen = len(mailString)
    if maxBytes>0 and mailLen>maxBytes:
        log_warning('Rejecting email, due to size (%s bytes, limit %s bytes)' %
                    (mailLen, maxBytes))
        event_codes.append(200) # email too long
        if not EVENT_NOTIFICATION:    
            sys.exit(EXIT_NOPERM)
        else:
            eventNotification(baseURL, event_codes, mailString)
            sys.exit(0)
    

    # Transfer mail to http-server.
    # urllib2 handles server-responses (errors) much better than urllib.
            
    # urllib2 is, in fact, too much better. Its built-in redirect handler
    # can mask authorization problems when a cookie-based authenticator is in
    # use -- as with Plone. Also, I can't think of any reason why we would
    # want to allow redirection of these requests!
    #
    # So, let's create and install a disfunctional redirect handler.
            
    # Install the broken redirect handler
    opener = urllib2.build_opener(BrokenHTTPRedirectHandler())
    urllib2.install_opener(opener)

    try:
        req = urllib2.Request(callURL)
        if AUTHORIZATION:
            auth = base64.encodestring(AUTHORIZATION).strip()
            req.add_header('Authorization', 'Basic %s' % auth)
        response = urllib2.urlopen(req, data='Mail='+urllib.quote(mailString)) 
    except Exception, e:
        # If MailBoxer doesn't exist, bounce message with EXIT_NOUSER,
        # so the sender will receive a "user-doesn't-exist"-mail from MTA.
        if hasattr(e, 'code'):
            if e.code == 404:
                raise Exception("URL at %s doesn't exist (%s)" % (callURL, e))
            else:
                # Server down? EXIT_TEMPFAIL causes the MTA to try again later.
                raise Exception('A problem, "%s", occurred uploading email to URL %s (error code was %s)' % (e, callURL, e.code))
        else:
            # Server down? EXIT_TEMPFAIL causes the MTA to try again later.
            raise Exception('A problem, "%s", occurred uploading email to server %s' % (e, callURL))

    if event_codes:
        eventNotification(baseURL, event_codes, mailString)

    # All locks will be removed when Python cleans up!

    mail = response.headers.get('Set-Cookie')
    if mail:
        from Cookie import BaseCookie
        cookie = BaseCookie(mail)
        try:
            morsel = cookie['debug-mail-location']
        except KeyError:
            return
        return morsel.value
