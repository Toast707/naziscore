# -*- coding:utf-8 -*-

import datetime
import json
import logging
import webapp2

from google.appengine.api import memcache
from google.appengine.api import urlfetch
from google.appengine.ext import ndb

from naziscore.models import Score
from naziscore.scoring import (
    calculated_score,
    get_score_by_screen_name,
    get_score_by_twitter_id,
)
from naziscore.twitter import (
    get_profile,
    get_timeline,
)


class ScoreByNameHandler(webapp2.RequestHandler):

    @ndb.toplevel
    def get(self, screen_name):
        self.response.headers['Content-Type'] = 'application/json'
        screen_name = screen_name.lower()
        result = memcache.get('screen_name:' + screen_name)
        if result is None:
            # We don't have a cached result.
            score = get_score_by_screen_name(screen_name, depth=0).get_result()
            if score is None:
                # We don't have a precalculated score.
                result = json.dumps(
                    {'screen_name': screen_name,
                     'last_updated': None}, encoding='utf-8')
            else:
                # We have a score in the datastore.
                result = json.dumps(
                    {'screen_name': score.screen_name,
                     'twitter_id': score.twitter_id,
                     'last_updated': score.last_updated.isoformat(),
                     'score': score.score},
                    encoding='utf-8')
                memcache.set('screen_name:' + screen_name, result, 3600)
        self.response.out.write(result)


class ScoreByIdHandler(webapp2.RequestHandler):

    @ndb.toplevel
    def get(self, twitter_id):
        self.response.headers['Content-Type'] = 'application/json'
        twitter_id = int(twitter_id)
        result = memcache.get('twitter_id:{}'.format(twitter_id))
        if result is None:
            # We don't have a cached result.
            score = get_score_by_twitter_id(twitter_id, depth=0).get_result()
            if score is None:
                # We don't have a precalculated score.
                result = json.dumps(
                    {'twitter_id': twitter_id,
                     'last_updated': None}, encoding='utf-8')
            else:
                # We have a score in the datastore.
                result = json.dumps(
                    {'screen_name': score.screen_name,
                     'twitter_id': score.twitter_id,
                     'last_updated': score.last_updated.isoformat(),
                     'score': score.score}, encoding='utf-8')
                memcache.set('twitter_id:{}'.format(twitter_id), result, 3600)
        self.response.out.write(result)


class CalculationHandler(webapp2.RequestHandler):
    """
    Makes requests to the Twitter API to retrieve the score.
    """
    @ndb.toplevel
    def post(self):
        # TODO: Here we get the user's stream, profile and calculate their nazi
        # score aplying the criteria functions on the data and adding the
        # results.
        screen_name = self.request.get('screen_name')
        twitter_id = self.request.get('twitter_id')
        depth = int(self.request.get('depth'))
        if screen_name != '':
            screen_name = screen_name.lower()
            score = get_score_by_screen_name(screen_name, depth).get_result()
        elif twitter_id != '':
            twitter_id = int(twitter_id)
            score = get_score_by_twitter_id(twitter_id, depth).get_result()
        if score is None or score.last_updated < (
                datetime.datetime.now() - datetime.timedelta(days=7)):
            # We'll need the profile and timeline data.
            try:
                profile = get_profile(screen_name, twitter_id)
            except urlfetch.httplib.HTTPException as e:
                profile = None
                if 'User has been suspended.' in e.message:
                    logging.warning('{} has been suspended'.format(
                        screen_name if screen_name else twitter_id))
                elif 'User not found.' in e.message:
                    logging.warning('{} does not exist'.format(
                        screen_name if screen_name else twitter_id))
                else:
                    raise  # Will retry later.
            if profile is not None:
                timeline = get_timeline(screen_name, twitter_id)

            else:
                timeline = None

            if score is None and profile is not None:
                # We need to add a new one, but only if we got something back.
                if screen_name == '':
                    screen_name = json.loads(profile)['screen_name']
                elif twitter_id == '':
                    twitter_id = json.loads(profile)['id']
                grades = calculated_score(profile, timeline, depth)
                Score(screen_name=screen_name,
                      twitter_id=twitter_id,
                      grades=grades,
                      profile_text=profile,
                      timeline_text=timeline).put()

            elif score is not None and score.last_updated < (
                    datetime.datetime.now() - datetime.timedelta(days=7)):
                # We need to either update or create a new one.
                    if timeline is not None:
                        grades = calculated_score(profile, timeline, depth)
                        score.grades = grades
                        score.put()
        else:
            # We have an up-to-date score. Nothing to do.
            pass
