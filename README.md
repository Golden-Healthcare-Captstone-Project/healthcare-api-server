# Golden Healthcare API Server

Backend API for the Golden Healthcare Community Care Hub.

The API is built with FastAPI and provides endpoints for services, service requests, payments, Meta integration, and the community feed.

## Running Locally

Start the API server with:

    uvicorn app.main:app --reload

The API will run at:

    http://127.0.0.1:8000

Interactive API documentation is available at:

    http://127.0.0.1:8000/docs

## Community Feed API

### GET /feed

Returns community feed posts ordered from newest to oldest.

Query parameters:

- `page` - Page number. Default: `1`
- `limit` - Number of posts per page. Default: `10`, maximum: `50`

Example:

    GET /feed?page=1&limit=10

Example response:

    {
      "posts": [
        {
          "id": "1",
          "author": {
            "id": "1",
            "name": "Juan Test",
            "avatarUrl": "",
            "role": "caregiver"
          },
          "text": "Community feed post",
          "createdAt": "2026-10-03T12:00:00",
          "likeCount": 0,
          "commentCount": 0,
          "shareCount": 0,
          "likedByCurrentUser": false
        }
      ],
      "page": 1,
      "limit": 10,
      "total": 1,
      "hasNext": false
    }

### POST /feed

Creates a new community feed post.

Authentication is currently handled using the temporary `x-user-id` request header. The authenticated user becomes the author of the post.

Required header:

    x-user-id: 1

Request body:

    {
      "text": "Community feed post"
    }

Successful requests return HTTP `201 Created`.

Possible responses:

- `201` - Post created successfully
- `401` - Authentication required
- `422` - Invalid post data, including empty or whitespace-only text

Post text must contain at least one non-whitespace character and cannot exceed 2000 characters.

## Tests

Install development dependencies:

    pip install -r requirements-dev.txt

Run all automated tests:

    pytest

Run only the community feed tests:

    pytest tests/test_feed.py -v