# Convert tweets to feed

This application converts twitter tweets to ATOM feeds.
It depends on twitter API and It uses specific list.

`/` clowl twitter to check new tweets using list.
`/add/id/{id}` add to list for check.
`/add/name/{screen_name}` add to list for check with sceen name.
`/id/{id}` shows feed.
`/name/{screen_name}` moves to feed with user id.

### requires

* Twitter application account.
* Dynamo DB tables.
`TwitterFeedSpecificIds` with string patition key `name`
`TwitterFeedStatuses` with number partition key `user_id` and number sort key `tweet_id`

#### deploy

1. set up apex http://apex.run/
2. execut init to create iam role. input project name you like.
```
apex init
```
3. remove created `hello` project.
4. execute apex with variables:
```
apex deploy -s CONSUMER_KEY=... -s CONSUMER_SECRET=...
```
* CONSUMER_KEY
* CONSUMER_SECRET
* ACCESS_TOKEN
* ACCESS_TOKEN_SECRET
* HOST
5. set CloudWatch and API Gateway manually.
