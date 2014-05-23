#!/usr/bin/python -B
# -*- coding: utf-8 -*-

"""
OSG-Software Google Calendar Triage assignment tool

Usage:
  $ ./triage.py OPTIONS

Examples:
  $ ./triage.py --list
  $ ./triage.py --list --minDate 2014-03-01 --maxDate 2014-04-20
  $ ./triage.py --list --calendarId primary
  $ ./triage.py --assign 2014-07-28 "James Kirk"
  $ ./triage.py --delete 2014-07-28
  $ ./triage.py --delete ALL --minDate 2014-07-01 --maxDate 2014-08-01
  $ ./triage.py --generate "User One" "User Two" "User Three" \ 
                --minDate 2014-05-01 --maxDate 2014-07-01 > list.txt
  $ ./triage.py --load list.txt
  $ ./triage.py --generate Fred Barney Dino \ 
                --minDate 2014-05-01 --maxDate 2014-07-01 | ./triage --load -


"""

import sys
import argparse
import datetime
import itertools
import re
import os.path

from apiclient           import sample_tools
from oauth2client.client import AccessTokenRefreshError

OSG_CAL_ID = "h5t4mns6omp49db1e4qtqrrf4g@group.calendar.google.com"
ROTATION_FILE = os.path.join(os.path.dirname(__file__), "rotation.txt")

def argparse_setup():
    ap = argparse.ArgumentParser(add_help=False)

    ap.add_argument('--calendarId', type=str, default=None, metavar='CALID',
        help="google calendar id to use.  Default is OSG Software "
             "calendar.  Use 'primary' for current user's "
             "calendar, or the google account name (eg, "
             "user@gmail.com) for another specific calendar.")

    start_mx  = ap.add_mutually_exclusive_group()
    end_mx    = ap.add_mutually_exclusive_group()
    action_mx = ap.add_mutually_exclusive_group()

    action_mx.add_argument('--list', action='store_true', default=False,
        help="list current assignments")

    start_mx.add_argument('--minDate', type=str, default=None, metavar='DATE',
        help="don't list assignments starting before YYYY-MM[-DD]")

    start_mx.add_argument('--extend', action='store_true', default=False,
        help="set minDate to start just after the last assignment")

    end_mx.add_argument('--maxDate', type=str, default=None, metavar='DATE',
        help="don't list assignments starting after YYYY-MM[-DD]")

    end_mx.add_argument('--weeks', type=int, default=None, metavar='N',
        help="set maxDate to limit to N weeks of assignments")

    end_mx.add_argument('--cycles', type=int, default=None, metavar='N',
        help="set weeks to N * number of names to generate")

#   mx = ap.add_mutually_exclusive_group()
#   mx.add_argument('--force', action='store_true', default=False,
#                   help="overwrite existing assignments")
#   mx.add_argument('--nocheck', action='store_true', default=False,
#                   help="don't check to see if new assignments"
#                   " are for the same dates as existing ones")

    action_mx.add_argument('--assign', type=str, nargs=2,
        metavar=('DATE','NAME'), help="assign name for date")

    action_mx.add_argument('--delete', type=str, default=None, metavar='DATE',
        help="delete assignment for date, or all assignments in "
             "minDate-maxDate range if date is \"ALL\"")

    action_mx.add_argument('--load', default=None, type=argparse.FileType('r'),
        metavar='FILE', # nargs='+',
        help='load "DATE: NAME" lines from file')

    action_mx.add_argument('--generate', default=None, type=str,
        metavar='NAME', nargs='*',
        help='output a list of "DATE: NAME" lines for Mondays in '
             'minDate-maxDate range')

    action_mx.add_argument('--generateFrom', default=None,
        type=argparse.FileType('r'), metavar='FILE',
        help='like generate, but get list of names from FILE')

    action_mx.add_argument('--generateRotation', action='store_true',
        default=False, help='same as --generateFrom=rotation.txt')

    action_mx.add_argument('--generateNextRotation', action='store_true',
        default=False, help='same as --generateRotation --extend --cycles=1')

    return ap

def main(argv):
    # make these globals for interactive use
    if __name__ != '__main__':
        global service
        global flags

    # if first arg is not a flag, interpret as an action
    if (len(argv) > 1 and not argv[1].startswith("-")):
        argv[1] = "--" + argv[1]

    service,flags = sample_tools.init(argv,'calendar','v3',__doc__,__file__,
                                        parents=[argparse_setup()])

    calId   = flags.calendarId or OSG_CAL_ID
    minDate = check_date(flags.minDate)
    maxDate = check_date(flags.maxDate)

    try:
        # options

        if flags.generateNextRotation:
            flags.generateRotation = True
            flags.extend = True
            if flags.cycles is None:
                flags.cycles = 1

        if flags.generateRotation:
            flags.generateFrom = open(ROTATION_FILE)

        if flags.generateFrom:
            flags.generate = [
                line.strip() for line in flags.generateFrom
                if  re.search(r'\S', line)      # skip blank lines
                and re.search(r'^[^#]', line)   # skip comment lines
            ]

        if flags.cycles is not None:
            if not flags.generate:
                fail("For --cycles, must specify one of the generate options "
                     "with a non-empty list of names.")

            flags.weeks = flags.cycles * len(flags.generate)

        if flags.extend:
            all_triages = get_triage_assignments(service, calId)
            if len(all_triages) == 0:
                fail("No triage assignments found, can't extend.")

            lastdate = s2d(all_triages[-1]['start'])
            one_week = datetime.timedelta(7)
            minDate  = d2s(lastdate + one_week)

        if flags.weeks is not None:
            if not minDate:
                fail("--weeks requires a minDate")

            one_week = datetime.timedelta(7)
            maxDate = s2d(minDate) + one_week * (flags.weeks - 1)
            maxDate = d2s(maxDate)

        # actions

        if flags.delete:
            if flags.delete == "ALL":
                if minDate and maxDate:
                    delete_triage_assignments(service, calId, minDate, maxDate)
                else:
                    fail("--delete ALL requires --minDate and --maxDate")
            else:
                date = check_date(flags.delete)
                delete_triage_assignment(service, calId, date)

        if flags.assign:
            date,name = flags.assign
            date = check_date(date)
            add_triage_assignment_1w(service, calId, name, date)

        if flags.load:
            file_handle = flags.load
            load_triage_assignments(service, calId, file_handle)

        if flags.list:
            list_triage_assignments(service, calId, minDate, maxDate)

        if flags.generate is not None:
            if minDate and maxDate:
                names = flags.generate
                generate_triage_assignments(names, minDate, maxDate)
            else:
                fail("--generate requires --minDate and --maxDate")

    except AccessTokenRefreshError:
        print ("The credentials have been revoked or expired, please re-run "
               "the application to re-authorize")

def generate_triage_assignments(names, minDate, maxDate):
    if len(names) == 0:
        names = ['']

    date = s2d(minDate)
    end  = s2d(maxDate)

    one_day  = datetime.timedelta(1)
    one_week = datetime.timedelta(7)

    while date.isoweekday() != 1:
        date += one_day

    for name in itertools.cycle(names):
        if date > end:
            break
        print "%s: %s" % (d2s(date), name)
        date += one_week


def load_triage_assignments(service, calId, file_handle):
    for line in file_handle:
        if re.search(r'^\s*$', line):
            continue
        m = re.search(r'^\s*(20\d{2}-\d{1,2}-\d{1,2}):\s*(.*\S)\s*$', line)
        if m is None:
            warn("skipping line: '%s'" % line.rstrip("\n"))
        else:
            date,name = m.groups()
            date = check_date(date)
            add_triage_assignment_1w(service, calId, name, date)

def add_triage_assignment(service, calId, name, start, end):

    event = {
        'summary': "Triage: " + name,
        'start':   {'date': start},
        'end':     {'date': end},
        'transparency': 'transparent'  # ie, show as available
    }

    ins = service.events().insert(calendarId=calId, body=event)          
    ret = ins.execute()
    #for x in ['summary','start','end','htmlLink']:
    for x in ['htmlLink']:
        print "%s: %s" % (x,ret[x])

def add_triage_assignment_1w(service, calId, name, start):
    start_dt = s2d(start)
    if start_dt.isoweekday() != 1:
        warn("%s is not a Monday, skipping..." % start)
    else:
        td = datetime.timedelta(5)  # Mon-Fri
        end = d2s(start_dt + td)
        print "adding assignment: %s: %s" % (start,name)
        add_triage_assignment(service, calId, name, start, end)

def warn(msg):
    sys.stderr.write(msg + "\n")

def fail(msg):
    warn(msg)
    sys.exit(1)

def s2d(s):
    m = re.search(r'^20\d\d-\d+$', s)
    datefmt = "%Y-%m" if m else "%Y-%m-%d"
    return datetime.datetime.strptime(s, datefmt)

def d2s(d):
    return d.strftime("%Y-%m-%d")

def check_date(s):
    if s is not None:
        try:
            return d2s(s2d(s))
        except ValueError:
            fail("malformed date string: '%s'" % s)

def delete_event(service, calId, item):
    service.events().delete(calendarId=calId, eventId=item["id"]).execute()

def delete_triage_assignment(service, calId, date):
    delete_triage_assignments(service, calId, date, date)

def delete_triage_assignments(service, calId, minStart, maxStart):
    triage = get_triage_assignments(service, calId, minStart, maxStart)
    l = len(triage)
    print "Found %d event%s to delete in time window." % (l, "s" * (l != 1))

    for item in triage:
        print "Deleting assignment: %s: %s" % (item['start'], item['summary'])
        delete_event(service, calId, item)

def get_triage_assignments(service, calId, minStart=None, maxStart=None):
    l = service.events().list(calendarId=calId)
    ret = l.execute()
    items = ret['items']

    def xfilters(filters,seq):
        """
        like filter(), but return items for which each filter returns true
        """
        for x in seq:
            for f in filters:
                if not f(x):
                    break
            else:
                yield x

    def istriage(item):
        return re.search('^Triage:', item['summary'])

    def date_or_datetime(t):
        return t.get('date') or t.get('dateTime')

    def timefield(key):
        return lambda item : date_or_datetime(item[key])

    def start_ge(date):
        return lambda item : date_or_datetime(item['start']) >= date

    def start_le(date):
        return lambda item : date_or_datetime(item['start']) <= date

    filters = [istriage]
    if minStart is not None:
        filters.append(start_ge(check_date(minStart)))

    if maxStart is not None:
        filters.append(start_le(check_date(maxStart)))

    triage = sorted(xfilters(filters,items),key=timefield('start'))

    triage = [ {'start'   : x['start'].get('date'),
                'summary' : re.sub('^Triage: *', '', x['summary']),
                'id'      : x['id']} for x in triage ]

    return triage

def list_triage_assignments(service, calId, minStart=None, maxStart=None):
    triage = get_triage_assignments(service, calId, minStart, maxStart)

    print "Triage:"
    for x in triage:
        print ("%s: %s" % (x['start'], x['summary'])).encode('utf-8')

if __name__ == '__main__':
  main(sys.argv)

