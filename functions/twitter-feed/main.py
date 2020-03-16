import json
import logging
import os
import re
import datetime

import requests
from requests_oauthlib import OAuth1Session

import boto3
from boto3.dynamodb.conditions import Key, Attr

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handle(event, context):
    """
    Lambda handler
    """

    if event.get("path", "").startswith("/name/"):
        return redirect_to_id(event["pathParameters"]["name"])

    if event.get("path", "").startswith("/id/"):
        return return_feed(event["pathParameters"]["id"])

    if event.get("path", "").startswith("/add/name/"):
        return redirect_to_add_id(event["pathParameters"]["name"])

    if event.get("path", "").startswith("/add/id/"):
        return add_id(event["pathParameters"]["id"])

    # fetch
    # get list status
    since_id = get_since_id()
    url = "https://api.twitter.com/1.1/lists/statuses.json?tweet_mode=extended&list_id="+initialize_list_id()
    if since_id:
        url = url + "&since_id=" + str(since_id)
    json = twitter_request().get(url).json()

    if not json:
        return "none"

    storage_statuses(json)

    update_since_id(json)
    notify_push(json)

    return json


def twitter_request():
    return OAuth1Session(
        os.environ["CONSUMER_KEY"],
        client_secret=os.environ["CONSUMER_SECRET"],
        resource_owner_key=os.environ["ACCESS_TOKEN"],
        resource_owner_secret=os.environ["ACCESS_TOKEN_SECRET"]
    )


def initialize_list_id():
    dynamoDB = boto3.resource("dynamodb")
    table = dynamoDB.Table("TwitterFeedSpecificIds")
    queryData = table.query(
        KeyConditionExpression=Key('name').eq("listId"),
        Limit=1
    )

    if(queryData["Items"]):
        return queryData["Items"][0]["value"]
    else:
        list_id = get_list_id()
        table.put_item(
            Item={
                'name': "listId",
                'value': list_id
            }
        )
        return list_id

def get_since_id():
    dynamoDB = boto3.resource("dynamodb")
    table = dynamoDB.Table("TwitterFeedSpecificIds")
    queryData = table.query(
        KeyConditionExpression=Key('name').eq("sinceId"),
        Limit=1
    )

    if(queryData["Items"]):
        return queryData["Items"][0]["value"]
    else:
        return None

def get_list_id():
    logger.info("getting list id")
    resp = twitter_request().get("https://api.twitter.com/1.1/lists/list.json")
    list_id = [x for x in resp.json() if x["name"] ==
               "use_to_feed"][0]["id_str"]
    return list_id


def storage_statuses(statuses):
    dynamoDB = boto3.resource("dynamodb")
    table = dynamoDB.Table("TwitterFeedStatuses")

    with table.batch_writer(overwrite_by_pkeys=['user_id', 'tweet_id']) as batch:
        for e in statuses:
            batch.put_item(Item={
                'user_id': e["user"]["id"],
                'tweet_id': e["id"],
                'json': json.dumps(e)
            })

def update_since_id(statuses):
    since_id = max([ t["id"] for t in statuses ])
    dynamoDB = boto3.resource("dynamodb")
    table = dynamoDB.Table("TwitterFeedSpecificIds")
    table.put_item(
        Item={
            'name': "sinceId",
            'value': since_id
        }
    )

def notify_push(statuses):
    for uid in set([ t["user"]["id"] for t in statuses ]):
        requests.post(
            "https://pubsubhubbub.appspot.com/publish",
            {
                "hub.mode": "publish",
                "hub.url": "https://"+os.environ["HOST"]+"/feed/id/"+str(uid)
            }
        )

def get_user_id(name):
    return twitter_request().get("https://api.twitter.com/1.1/users/show.json?screen_name="+name).json()["id_str"]


def redirect_to_id(name):
    return {
        "statusCode": 302,
        "headers": {
            "Location":
            "https://"+os.environ["HOST"]+"/feed/id/"+get_user_id(name)
        }
    }


def redirect_to_add_id(name):
    return {
        "statusCode": 302,
        "headers": {
            "Location":
            "https://"+os.environ["HOST"]+"/feed/add/id/"+get_user_id(name)
        }
    }


def return_feed(uid):
    tweets = get_storaged_tweets(uid)

    first_tweet = tweets[0]
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<title>Twitter Timeline Feed for {name}</title>
<link href="http://twitter.com/{screen_name}"/>
<link type="application/atom+xml" rel="self" href="https://{host}/feed/id/{id}"/>
<link rel="hub" href="http://pubsubhubbub.appspot.com"/>
<summary>Twitter Timeline Feed for {name}</summary>
<updated>{updated}</updated>
<id>https://{host}/feed/id/{id}</id>""".format(
        name=xmltext(first_tweet["user"]["name"]),
        screen_name=first_tweet["user"]["screen_name"],
        id=first_tweet["user"]["id_str"],
        updated=datetime.datetime.strptime(
            first_tweet["created_at"], '%a %b %d %X %z %Y').isoformat(),
        host=os.environ["HOST"]
    )
    for e in tweets:
        tweet_link = "https://twitter.com/"+e["user"]["screen_name"]+"/status/"+e["id_str"]
        link = tweet_link
        if len(e["entities"]["urls"]) == 1:
            link = e["entities"]["urls"][0]["expanded_url"].replace("&", "&amp;")

        xml += """
<entry>
<title>{text}</title>
<link href="{link}"/>
<id>{tweet_link}</id>
<summary type="html">
<div>{text}</div>
<div><a href="{tweet_link}">tweet</a></div>
</summary>
<updated>{updated}</updated>
<author>
<name>{name}</name>
<uri>http://twitter.com/{screen_name}</uri>
</author>
</entry>""".format(
            name=xmltext(e["user"]["name"]),
            screen_name=e["user"]["screen_name"],
            id=e["id_str"],
            updated=datetime.datetime.strptime(
                e["created_at"], '%a %b %d %X %z %Y').isoformat(),
            text=xmltext(e["full_text"]),
            tweet_link=tweet_link,
            link=link
        )

    xml += "</feed>"

    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/xml"
        },
        "body": xml
    }


def get_storaged_tweets(uid):
    dynamoDB = boto3.resource("dynamodb")
    table = dynamoDB.Table("TwitterFeedStatuses")

    return [json.loads(e["json"]) for e in table.query(
        KeyConditionExpression=Key('user_id').eq(int(uid)),
        ScanIndexForward=False,
        Limit=50
    )["Items"]]


def xmltext(s):
    r = ""
    for a in s:
        r += "&#"+str(ord(a))+";"
    return r


def add_id(uid):
    # add list
    twitter_request().post("https://api.twitter.com/1.1/lists/members/create.json?list_id="+initialize_list_id()+"&user_id="+uid)

    # fetch tweets
    json = twitter_request().get("https://api.twitter.com/1.1/statuses/user_timeline.json?tweet_mode=extended&count=50&user_id="+uid).json()
    if json:
        storage_statuses(json)

    return {
        "statusCode": 302,
        "headers": {
            "Location": "https://"+os.environ["HOST"]+"/feed/id/"+uid
        }
    }
