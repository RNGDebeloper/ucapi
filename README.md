# Surf-TG Backend API

Surf-TG is a **JSON-only backend service** for Telegram-backed file indexing and delivery. It runs a Python/aiohttp server plus Telegram bot clients that can:

- index files from configured Telegram channels;
- browse indexed Telegram channels and database playlist folders;
- search channel files and playlist files;
- manage playlist folders and file metadata as an admin;
- serve thumbnails;
- stream or download Telegram files with HTTP byte-range support.

Treat the server as an authenticated backend/API surface that a separate web, mobile, or desktop frontend can call. List and search file objects include `tmdb_id` (or `null` when no match is available), `tmdb_type`, `season`, `episode`, and `poster_url`. Set a Telegram media caption to `{tmdb_id}/{season}/{episode}` (for example, `262838/2/1`) to identify a TV episode directly; the JSON response returns those values as numeric `tmdb_id`, `season`, and `episode` fields.

## Environment variables

Surf-TG reads environment variables directly and also loads a local `config.env` file when present. For local development, create `config.env` in the project root and set the variables you need.

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `API_ID` | Yes | `0` | Telegram `api_id` from <https://my.telegram.org/apps>. |
| `API_HASH` | Yes | empty | Telegram `api_hash` from <https://my.telegram.org/apps>. |
| `BOT_TOKEN` | Yes | empty | Telegram bot token from BotFather. The bot must be able to access indexed channels. |
| `AUTH_CHANNEL` | Yes | empty | Comma-separated Telegram channel IDs used as source indexes, for example `-1001234567890,-1009876543210`. |
| `DATABASE_URL` | Yes | empty | MongoDB connection string used for playlist folders/files and runtime configuration. |
| `BASE_URL` | Yes | empty | Public base URL for the deployed service, without a trailing slash. |
| `PORT` | No | `8080` | TCP port used by the aiohttp server. |
| `SESSION_STRING` | No | empty | Optional Pyrogram user session string. When set, the user client is started alongside the bot client. |
| `USERNAME` | No | `admin` | Standard authenticated username for browsing/searching/watching. |
| `PASSWORD` | No | `admin` | Password for `USERNAME`. Change this in every deployment. |
| `ADMIN_USERNAME` | No | `surfTG` | Admin username. Required for playlist/config mutation routes. Make it different from `USERNAME`. |
| `ADMIN_PASSWORD` | No | `surfTG` | Password for `ADMIN_USERNAME`. Change this in every deployment. |
| `THEME` | No | `vapor` | Legacy configuration value retained for compatibility; it is not used by JSON responses. |
| `SLEEP_THRESHOLD` | No | `60` | Pyrogram flood-wait sleep threshold. |
| `WORKERS` | No | `10` | Maximum concurrent worker count for incoming Telegram updates. |
| `MULTI_CLIENT` | No | `False` | Enables worker bot clients when truthy in the app logic. |
| `MULTI_TOKEN1`, `MULTI_TOKEN2`, ... | No | unset | Optional additional bot tokens for multi-client streaming/indexing. Add each worker bot to `AUTH_CHANNEL`. |
| `HIDE_CHANNEL` | No | `False` | Legacy configuration value retained for compatibility. |
| `TMDB_API_KEY` | No | empty | TMDb API key used to add `tmdb_id`, `tmdb_type`, and `poster_url` to indexed and user-session file results. Without it, `tmdb_id` is `null` and the fallback poster is returned. |

## Local, Docker, and Heroku deployment

### Local development

```sh
git clone https://github.com/weebzone/Surf-TG
cd Surf-TG
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp sample_config.env config.env 2>/dev/null || touch config.env
# edit config.env with your Telegram, MongoDB, and auth settings
python3 -m bot
```

The server binds to `0.0.0.0:$PORT` and defaults to port `8080`.

### Docker

```sh
git clone https://github.com/weebzone/Surf-TG
cd Surf-TG
# create config.env or pass environment variables with -e/--env-file
docker build -t surf-tg .
docker run --env-file config.env -p 8080:8080 surf-tg
```

You can also use Compose:

```sh
docker compose up --build
```

### Heroku

The repository includes both `Procfile` and `heroku.yml` definitions that run `bash surf-tg.sh`. Configure all required environment variables as Heroku config vars before starting the app.

```sh
heroku create your-surf-tg-app
heroku stack:set container
heroku config:set API_ID=... API_HASH=... BOT_TOKEN=... AUTH_CHANNEL=... DATABASE_URL=... BASE_URL=https://your-surf-tg-app.herokuapp.com
heroku config:set USERNAME=... PASSWORD=... ADMIN_USERNAME=... ADMIN_PASSWORD=...
git push heroku HEAD:main
```

## Authentication flow

Surf-TG uses cookie-backed aiohttp sessions.

1. Protected browse, search, and watch routes return `401 Unauthorized` JSON until a session is authenticated.
2. `POST /login` accepts form fields `username` and `password`.
3. If the submitted credentials match either `USERNAME`/`PASSWORD` or `ADMIN_USERNAME`/`ADMIN_PASSWORD`, the server stores `session['user'] = username` and returns JSON confirming the authentication state.
4. Admin-only routes require `session['user'] == ADMIN_USERNAME` and return `{"msg":"Who the hell you are"}` when called by a non-admin or anonymous session.
5. `POST /logout` removes `session['user']` and returns JSON confirming the session is unauthenticated.

### Auth categories used below

- **Public**: no login session required.
- **User**: requires either standard or admin login.
- **Admin**: requires admin login.

## API endpoint reference

All non-streaming endpoints return `application/json`. Protected endpoints return `401` with `{"error": "Authentication required"}` when no authenticated session is present.

### `POST /login`

- **Auth**: Public.
- **Body**: `application/x-www-form-urlencoded` or multipart form.

| Field | Required | Description |
| --- | --- | --- |
| `username` | Yes | Either `USERNAME` or `ADMIN_USERNAME`. |
| `password` | Yes | Matching password. |

- **Success**: `200 OK application/json` with `{"authenticated": true, "is_admin": false}` (or `true` for an admin); sets a session cookie.
- **Failure**: `401 Unauthorized application/json` with `{"authenticated": false, "error": "Invalid username or password"}`.

Example request:

```sh
curl -i -c cookies.txt -X POST http://localhost:8080/login \
  -d 'username=admin' \
  -d 'password=admin'
```

### `POST /logout`

- **Auth**: Public, but only affects the current session.
- **Body**: none.
- **Success**: `200 OK application/json` with `{"authenticated": false}`; removes the logged-in session user.

Example response: `{"authenticated": false}`.

### `GET /`

- **Auth**: User.
- **Query parameters**: none.
- **Success**: `200 OK application/json` containing channel cards and root playlist folders. Admin sessions receive `is_admin: true`.
- **Unauthenticated**: `401 Unauthorized application/json`.

### `GET /playlist?db={folder_id}&page={page}`

- **Auth**: User.
- **Query parameters**:

| Parameter | Required | Default | Description |
| --- | --- | --- | --- |
| `db` | Yes | none | Database playlist folder ID to open. |
| `page` | No | `1` | Pagination page. |

- **Success**: `200 OK application/json` containing child folders and files for `folder_id`.
- **Unauthenticated**: `401 Unauthorized application/json`.

### `GET /search/db/{parent}?q={query}&page={page}`

- **Auth**: User.
- **Path parameters**:

| Parameter | Description |
| --- | --- |
| `parent` | Playlist folder ID to search within. |

- **Query parameters**:

| Parameter | Required | Default | Description |
| --- | --- | --- | --- |
| `q` | Yes | none | Search query. |
| `page` | No | `1` | Pagination page. |

- **Success**: `200 OK application/json` playlist search results for the parent folder.

### `GET /channel/{chat_id}?page={page}`

- **Auth**: User.
- **Path parameters**:

| Parameter | Description |
| --- | --- |
| `chat_id` | Telegram channel ID without the `-100` prefix. The server adds `-100` internally. |

- **Query parameters**:

| Parameter | Required | Default | Description |
| --- | --- | --- | --- |
| `page` | No | `1` | Pagination page. |

- **Success**: `200 OK application/json` channel file listing.

### `GET /search/{chat_id}?q={query}&page={page}`

- **Auth**: User.
- **Path parameters**:

| Parameter | Description |
| --- | --- |
| `chat_id` | Telegram channel ID without the `-100` prefix. |

- **Query parameters**:

| Parameter | Required | Default | Description |
| --- | --- | --- | --- |
| `q` | Yes | none | Search query. |
| `page` | No | `1` | Pagination page. |

- **Success**: `200 OK application/json` channel search results.

### `GET /api/thumb/{chat_id}?id={message_id}`

- **Auth**: Public.
- **Path parameters**:

| Parameter | Description |
| --- | --- |
| `chat_id` | Telegram chat/channel ID as expected by thumbnail lookup. |

- **Query parameters**:

| Parameter | Required | Default | Description |
| --- | --- | --- | --- |
| `id` | No | none | Telegram message ID. If omitted, the route returns the chat/channel image when available. |

- **Success**: `200 OK image/jpeg` file response.

Example response headers:

```http
HTTP/1.1 200 OK
Content-Type: image/jpeg
```

### `GET /watch/{chat_id}?id={message_id}&hash={hash}`

- **Auth**: User.
- **Path parameters**:

| Parameter | Description |
| --- | --- |
| `chat_id` | Telegram channel ID without the `-100` prefix. |

- **Query parameters**:

| Parameter | Required | Description |
| --- | --- | --- |
| `id` | Yes | Telegram message ID for the file. |
| `hash` | Yes | First six characters of the Telegram file unique ID. Used as a lightweight access/integrity check by the stream route. |

- **Success**: `200 OK application/json` with the validated file ID, hash, and `stream_url`.
- **Errors**: `401 Unauthorized` if unauthenticated.

### `GET /{chat_id}/{encoded_name}?id={message_id}&hash={hash}`

- **Auth**: Public.
- **Purpose**: Streams or downloads the Telegram file.
- **Path parameters**:

| Parameter | Description |
| --- | --- |
| `chat_id` | Telegram channel ID without the `-100` prefix. |
| `encoded_name` | Filename slug used in the URL. The handler does not currently use it to locate the file. |

- **Query parameters**:

| Parameter | Required | Description |
| --- | --- | --- |
| `id` | Yes | Telegram message ID for the file. |
| `hash` | Yes | First six characters of the Telegram file unique ID. |

- **Request headers**:

| Header | Required | Description |
| --- | --- | --- |
| `Range` | No | Byte range such as `bytes=0-1048575`. |

- **Success**: `200 OK` for full responses when no `Range` header is sent, or `206 Partial Content` when `Range` is present.
- **Response headers**: `Content-Type`, `Content-Range`, `Content-Length`, `Content-Disposition: attachment; filename="..."`, and `Accept-Ranges: bytes`.
- **Errors**: `403 Forbidden` for invalid hash, `404 Not Found` for missing Telegram file, `416 Range Not Satisfiable` for invalid byte ranges.

Example partial response:

```http
HTTP/1.1 206 Partial Content
Content-Type: video/mp4
Content-Range: bytes 0-1048575/734003200
Content-Length: 1048576
Content-Disposition: attachment; filename="movie.mp4"
Accept-Ranges: bytes
```

### `POST /create`

- **Auth**: Admin.
- **Body**: form data.

| Field | Required | Description |
| --- | --- | --- |
| `folderName` | Yes | New folder name. |
| `thumbnail` | No | Thumbnail URL/path stored with the folder. |
| `parent_dir` | Yes | Parent folder reference. Values containing `db=` are normalized to the ID after `db=`; otherwise the parent becomes `root`. |

- **Success**: `200 OK application/json` with `created: true` and `parent_folder`.
- **Non-admin**: JSON `{"msg":"Who the hell you are"}`.

### `POST /delete`

- **Auth**: Admin.
- **Body**: JSON.

| Field | Required | Description |
| --- | --- | --- |
| `delete_id` | Yes | Folder/file database ID to delete. |
| `parent` | Yes | Parent folder ID or `root`. |

- **Success**: `200 OK application/json` with `deleted: true` and `parent_folder`.
- **Failure**: `500 Internal Server Error` if database deletion fails.

### `POST /edit`

- **Auth**: Admin.
- **Body**: form data.

| Field | Required | Description |
| --- | --- | --- |
| `folder_id` | Yes | Folder database ID to edit. |
| `folderName` | Yes | Replacement folder name. |
| `thumbnail` | No | Replacement thumbnail. |
| `parent` | Yes | Parent folder ID or `root`. |

- **Success**: `200 OK application/json` with `updated: true` and `parent_folder`.
- **Failure**: `500 Internal Server Error` if update fails.

### `POST /edit_post`

- **Auth**: Admin.
- **Body**: form data.

| Field | Required | Description |
| --- | --- | --- |
| `file_id` | Yes | File database ID to edit. |
| `fileName` | Yes | Replacement file name. |
| `filethumbnail` | No | Replacement thumbnail. |
| `file_folder_id` | Yes | Parent folder ID or `root`. |

- **Success**: `200 OK application/json` with `updated: true` and `parent_folder`.
- **Failure**: `500 Internal Server Error` if update fails.

### `GET /searchDbFol?query={query}`

- **Auth**: Admin.
- **Query parameters**:

| Parameter | Required | Default | Description |
| --- | --- | --- | --- |
| `query` | No | empty string | Folder search text. |

- **Success**: `200 OK application/json` array/object returned by the database folder search helper.
- **Non-admin**: JSON `{"msg":"Who the hell you are"}`.

Example response shape:

```json
[
  {"id": "folder-id", "name": "Movies"}
]
```

The exact object fields depend on the database helper implementation.

### `POST /send`

- **Auth**: Public in the current route implementation. Frontends should treat this as sensitive and expose it only to trusted/admin users until server-side authorization is added.
- **Body**: form data.

| Field | Required | Description |
| --- | --- | --- |
| `chatId` | Yes | Telegram channel ID without `-100`; the route prepends `-100`. |
| `folderId` | Yes | Destination playlist folder ID or `root`. |
| `selectedIds` | Yes | Comma-separated entries. Each entry must be `file_id|hash|filename|size|file_type|thumbnail`. |

- **Success**: `200 OK application/json` with the number of created records and `parent_folder`.
- **Validation failure**: returns an error object from the handler if required form data is missing.

Example `selectedIds` value:

```text
123|abcdef|movie.mp4|734003200|video|https://example.com/thumb.jpg
```

### `GET /reload?chatId={chat_id}`

- **Auth**: Admin.
- **Query parameters**:

| Parameter | Required | Description |
| --- | --- | --- |
| `chatId` | Yes | Use `home` to clear global cache, or a channel ID without `-100` to clear that channel cache. |

- **Success**: `200 OK application/json` with the reloaded target.
- **Non-admin**: JSON `{"msg":"Who the hell you are"}`.

### `POST /config`

- **Auth**: Admin.
- **Body**: form data.

| Field | Required | Description |
| --- | --- | --- |
| `channel` | No | Replacement configured auth channel value stored in the database config. |
| `theme` | No | Replacement theme value stored in the database config. |

- **Success**: `200 OK application/json` with `updated: true`.
- **Failure**: `500 Internal Server Error` if config update fails.

## Streaming and download behavior

The download endpoint is `GET /{chat_id}/{encoded_name}?id={message_id}&hash={hash}`. The route uses the Telegram `chat_id`, `message_id`, and `hash` to load file metadata through `ByteStreamer`, validate the file hash, and stream bytes from Telegram to the HTTP client.

Important behavior for frontend/client implementers:

- `chat_id` values in URLs omit the `-100` prefix. The server prepends it internally.
- `hash` must equal the first six characters of the Telegram file's `unique_id`; otherwise the response is `403 Forbidden`.
- `encoded_name` is used for readable URLs but is not used to fetch the file.
- The server sends `Content-Disposition: attachment`, so browsers normally download the file. A separate frontend can still place the URL in media elements if the browser accepts the MIME type and headers.
- The response includes `Accept-Ranges: bytes`.
- Sending a `Range` request such as `Range: bytes=1048576-2097151` returns `206 Partial Content` with the requested byte window.
- Invalid ranges return `416 Range Not Satisfiable` with `Content-Range: bytes */{file_size}`.
- Without a `Range` header, the route returns status `200 OK` and streams the whole file while still including `Content-Range` and `Content-Length`.

Example range request:

```sh
curl -L -b cookies.txt \
  -H 'Range: bytes=0-1048575' \
  'http://localhost:8080/1234567890/movie.mp4?id=42&hash=abcdef' \
  -o movie.part
```

## Notes for building a separate frontend

- Use the backend as a session-cookie service. Log in with `POST /login`, store the returned cookie, and include it on User/Admin routes.
- Public media and thumbnail URLs can be fetched without a login session in the current implementation, but watch/list/search pages require login.
- Browse, search, login, watch, and mutation endpoints return JSON; thumbnail and streaming endpoints return the requested media bytes.
- Keep admin credentials and admin-only mutations away from untrusted clients. In particular, `POST /send` currently has no session check in the route handler and should be protected by your frontend/API gateway or fixed server-side before public exposure.
- Normalize channel IDs consistently: route URLs generally use the numeric channel ID without `-100`, while database records and Telegram client calls usually use `-100...`.
- Use the JSON authentication status and HTTP status codes directly; no redirect handling is required for API requests.
- For video players and resumable downloaders, prefer the direct `/{chat_id}/{encoded_name}` URL with `Range` requests and handle `206`, `416`, `403`, and `404` explicitly.
