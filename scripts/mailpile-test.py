#!/usr/bin/env python2
#
# This script runs a set of black-box tests on Mailpile using the test
# messages found in `testing/`.
#
# If run with -i as the first argument, it will then drop to an interactive
# python shell for experimenting and manual testing.
#
import os
import sys
import time
import traceback


# Set up some paths
mailpile_root = os.path.join(os.path.dirname(__file__), '..')
mailpile_test = os.path.join(mailpile_root, 'testing')
mailpile_send = os.path.join(mailpile_root, 'scripts', 'test-sendmail.sh')
mailpile_home = os.path.join(mailpile_test, 'tmp')
mailpile_gpgh = os.path.join(mailpile_test, 'gpg-keyring')
mailpile_sent = os.path.join(mailpile_home, 'sent.mbx')

# Set the GNUGPHOME variable to our test key
os.environ['GNUPGHOME'] = mailpile_gpgh

# Add the root to our import path, import API and demo plugins
sys.path.append(mailpile_root)
import mailpile.plugins.demos
from mailpile import Mailpile


##[ Black-box test script ]###################################################

FROM_BRE = [u'from:r\xfanar', u'from:bjarni']
MY_FROM = 'team+testing@mailpile.is'
MY_NAME = 'Mailpile Team'
MY_KEYID = '0x7848252F'

# First, we set up a pristine Mailpile
os.system('rm -rf %s' % mailpile_home)
mp = Mailpile(workdir=mailpile_home)
cfg = config = mp._session.config


def contents(fn):
    return open(fn, 'r').read()


def grep(w, fn):
    return '\n'.join([l for l in open(fn, 'r').readlines() if w in l])


def grepv(w, fn):
    return '\n'.join([l for l in open(fn, 'r').readlines() if w not in l])


def say(stuff):
    mp._session.ui.mark(stuff)
    mp._session.ui.reset_marks()


def do_setup():
    # Set up initial tags and such
    mp.setup()

    # Configure our fake mail sending setup
    mp.set('profiles/0/email = %s' % MY_FROM)
    mp.set('profiles/0/name = %s' % MY_NAME)
    mp.set('profiles/0/route = |%s -i %%(rcpt)s' % mailpile_send)
    mp.set('sys/debug = sendmail log compose')
    mp.set('prefs/openpgp_header = encrypt')
    mp.set('prefs/crypto_policy = openpgp-sign')

    # Set up dummy conctact importer fortesting, disable Gravatar
    mp.set('prefs/vcard/importers/demo/0/name = Mr. Rogers')
    mp.set('prefs/vcard/importers/gravatar/0/active = false')
    mp.set('prefs/vcard/importers/gpg/0/active = false')

    # Make sure that actually worked
    assert(not mp._config.prefs.vcard.importers.gpg[0].active)
    assert(not mp._config.prefs.vcard.importers.gravatar[0].active)

    # Add the mailboxes, scan them
    for mailbox in ('tests.mbx', 'Maildir'):
        mp.add(os.path.join(mailpile_test, mailbox))

def test_vcards():
    # Do we have a Mr. Rogers contact?
    mp.rescan('vcards')
    assert(mp.contact('mr@rogers.com'
                      ).result['contact']['fn'] == u'Mr. Rogers')
    assert(len(mp.contact_list('rogers').result['contacts']) == 1)

def test_load_save_rescan():
    mp.rescan()

    # Save and load the index, just for kicks
    messages = len(mp._config.index.INDEX)
    assert(messages > 5)
    mp._config.index.save(mp._session)
    mp._session.ui.reset_marks()
    mp._config.index.load(mp._session)
    mp._session.ui.reset_marks()
    assert(len(mp._config.index.INDEX) == messages)

    # Rescan AGAIN, so we can test for the presence of duplicates.
    mp.rescan()

    # Search for things, there should be exactly one match for each.
    mp.order('rev-date')
    for search in (FROM_BRE,
                   ['agirorn'],
                   ['subject:emerging'],
                   ['from:twitter', 'brennan'],
                   ['dates:2013-09-17', 'feministinn'],
                   ['mailbox:tests.mbx'] + FROM_BRE,
                   ['att:jpg', 'fimmtudaginn'],
                   ['subject:Moderation', 'kde-isl'],
                   ['from:bjarni', 'subject:testing', 'subject:encryption',
                    'should', 'encrypted', 'message', 'tag:mp_enc-decrypted'],
                   ['from:bjarni', 'subject:inline', 'subject:encryption',
                    'grand', 'tag:mp_enc-mixed-decrypted'],
                   ['from:bjarni', 'subject:signatures',
                    'tag:mp_sig-unverified'],
                   ['from:brennan', 'subject:encrypted',
                    'testing', 'purposes', 'only', 'tag:mp_enc-decrypted'],
                   ['from:brennan', 'subject:signed',
                    'tag:mp_sig-unverified'],
                   ['from:barnaby', 'subject:testing', 'soup',
                    'tag:mp_sig-unknown', 'tag:mp_enc-decrypted'],
                   ):
        say('Searching for: %s' % search)
        results = mp.search(*search)
        assert(results.result['stats']['count'] == 1)

    say('Checking size of inbox')
    mp.order('flat-date')
    assert(mp.search('tag:inbox').result['stats']['count'] == 13)

    say('FIXME: Make sure message signatures verified')

def test_message_data():
    # Load up a message and take a look at it...
    search_bre = mp.search(*FROM_BRE).result
    result_bre = search_bre['data']['metadata'][search_bre['thread_ids'][0]]
    view_bre = mp.view('=%s' % result_bre['mid']).result

    # Make sure message threading is working (there are message-ids and
    # references in the test data).
    assert(len(view_bre['thread_ids']) == 3)

    # Make sure we are decoding weird headers correctly
    metadata_bre = view_bre['data']['metadata'][view_bre['message_ids'][0]]
    message_bre = view_bre['data']['messages'][view_bre['message_ids'][0]]
    from_bre = search_bre['data']['addresses'][metadata_bre['from']['aid']]
    say('Checking encoding: %s' % from_bre)
    assert('=C3' not in from_bre['fn'])
    assert('=C3' not in from_bre['address'])
    for key, val in message_bre['header_list']:
        if key.lower() not in ('from', 'to', 'cc'):
            continue
        say('Checking encoding: %s: %s' % (key, val))
        assert('utf' not in val)

def test_composition():
    # Create a message...
    new_mid = mp.message_compose().result['thread_ids'][0]
    assert(mp.search('tag:drafts').result['stats']['count'] == 0)
    assert(mp.search('tag:blank').result['stats']['count'] == 1)
    assert(mp.search('tag:sent').result['stats']['count'] == 0)
    assert(not os.path.exists(mailpile_sent))

    # Edit the message (moves from Blank to Draft, not findable in index)
    msg_data = {
        'to': ['%s#%s' % (MY_FROM, MY_KEYID)],
        'bcc': ['secret@test.com#%s' % MY_KEYID],
        'mid': [new_mid],
        'subject': ['This the TESTMSG subject'],
        'body': ['Hello world!']
    }
    mp.message_update(**msg_data)
    assert(mp.search('tag:drafts').result['stats']['count'] == 1)
    assert(mp.search('tag:blank').result['stats']['count'] == 0)
    assert(mp.search('TESTMSG').result['stats']['count'] == 1)
    assert(not os.path.exists(mailpile_sent))

    # Send the message (moves from Draft to Sent, is findable via. search)
    del msg_data['subject']
    msg_data['body'] = ['Hello world: thisisauniquestring :)']
    mp.message_update_send(**msg_data)
    mp.sendmail()
    assert(mp.search('tag:drafts').result['stats']['count'] == 0)
    assert(mp.search('tag:blank').result['stats']['count'] == 0)
    assert('the TESTMSG subject' in contents(mailpile_sent))
    assert('thisisauniquestring' in contents(mailpile_sent))
    assert(MY_KEYID not in contents(mailpile_sent))
    assert(MY_FROM in grep('X-Args', mailpile_sent))
    assert('secret@test.com' in grep('X-Args', mailpile_sent))
    assert('secret@test.com' not in grepv('X-Args', mailpile_sent))
    for search in (['tag:sent'],
                   ['bcc:secret@test.com'],
                   ['thisisauniquestring'],
                   ['thisisauniquestring'] + MY_FROM.split(),
                   ['subject:TESTMSG']):
        say('Searching for: %s' % search)
        assert(mp.search(*search).result['stats']['count'] == 1)
    assert('thisisauniquestring' in contents(mailpile_sent))
    assert('OpenPGP: id=CF5E' in contents(mailpile_sent))
    assert('; preference=encrypt' in contents(mailpile_sent))
    assert('secret@test.com' not in grepv('X-Args', mailpile_sent))
    os.remove(mailpile_sent)

    # Test the send method's "bounce" capability
    mp.message_send(mid=[new_mid], to=['nasty@test.com'])
    mp.sendmail()
    assert('thisisauniquestring' in contents(mailpile_sent))
    assert('OpenPGP: id=CF5E' in contents(mailpile_sent))
    assert('; preference=encrypt' in contents(mailpile_sent))
    assert('secret@test.com' not in grepv('X-Args', mailpile_sent))
    assert('-i nasty@test.com' in contents(mailpile_sent))

def test_html():
    mp.output("jhtml")
    assert('&lt;bang&gt;' in '%s' % mp.search('in:inbox').as_html())
    mp.output("text")


try:
    do_setup()
    if '-n' in sys.argv:
        say("Skipping tests...")
    else:
        test_vcards()
        test_load_save_rescan()
        test_message_data()
        test_html()
        test_composition()
        say("Tests passed, woot!")
except:
    say("Tests FAILED!")
    print
    traceback.print_exc()


##[ Interactive mode ]########################################################

if '-i' in sys.argv:
    mp.set('prefs/vcard/importers/gravatar/0/active = true')
    mp.set('prefs/vcard/importers/gpg/0/active = true')
    mp.Interact()


##[ Cleanup ]#################################################################
os.system('rm -rf %s' % mailpile_home)
