# Surf-TG website API mapping

This is a frontend-oriented JSON map for every registered HTTP endpoint. The base URL in the examples is `https://api.example.com`. Send the session cookie returned by `POST /login` to every **User** or **Admin** request.

## Shared objects

### File

`title` is the **TMDb title** whenever the server found a TMDb match. `telegram_title` always preserves the cleaned Telegram caption or filename, so it can be used for diagnostics, download naming, or a fallback UI. When no TMDb title is available, `title` equals `telegram_title` and `tmdb_title` is `null`.

```json
{
  "id": 42,
  "file_id": 42,
  "chat_id": "-1001234567890",
  "public_chat_id": "1234567890",
  "title": "Daredevil",
  "telegram_title": "262838/2/1",
  "tmdb_title": "Daredevil",
  "tmdb_id": 262838,
  "tmdb_type": "tv",
  "season": 2,
  "episode": 1,
  "poster_url": "https://image.tmdb.org/t/p/w500/poster.jpg",
  "thumbnail": "https://image.tmdb.org/t/p/w500/poster.jpg",
  "size": "734.00MB",
  "file_size": "734.00MB",
  "mime_type": "video/mp4",
  "file_type": "video/mp4",
  "hash": "abcdef",
  "parent_folder": null,
  "type": "file",
  "stream_url": "/1234567890/stream?id=42&hash=abcdef",
  "watch_url": "/watch/1234567890?id=42&hash=abcdef"
}
```

For playlist files, `id` is the MongoDB object ID (a string), `file_id` is a Telegram message ID (usually a string), and `parent_folder` is the playlist ID. Their `name` is also included and equals the TMDb title when present.

### Standard errors

```json
{"error": "Authentication required"}
```

Unauthenticated User routes return that JSON with HTTP `401`. Admin routes instead currently return HTTP `200` with:

```json
{"msg": "Who the hell you are"}
```

## Authentication

### `GET /login` — public session state

**Request**

```http
GET /login
```

**Response — 200**

```json
{"authenticated": false}
```

### `POST /login` — public

Send form data, not a JSON body.

**Request**

```http
POST /login
Content-Type: application/x-www-form-urlencoded

username=admin&password=admin
```

**Response — 200** (also sets the session cookie)

```json
{"authenticated": true, "is_admin": false}
```

**Response — 401**

```json
{"authenticated": false, "error": "Invalid username or password"}
```

### `POST /logout` — public

**Request**

```http
POST /logout
```

**Response — 200**

```json
{"authenticated": false}
```

## Browse and search

### `GET /` — User

**Request**

```http
GET /
Cookie: session=...
```

**Response — 200**

```json
{
  "channels": [{"id": -1001234567890, "chat_id": -1001234567890, "public_id": "1234567890", "title": "Movies", "type": "CHANNEL", "thumbnail": "/api/thumb/-1001234567890", "url": "/channel/1234567890"}],
  "playlists": [{"id": "66abc...", "title": "Favorites", "name": "Favorites", "type": "folder", "thumbnail": null, "parent_folder": "root", "url": "/playlist?db=66abc..."}],
  "is_admin": false
}
```

### `GET /channel/{chat_id}?page=1` — User

`chat_id` omits Telegram's `-100` prefix. `page` defaults to `1`.

**Request**

```http
GET /channel/1234567890?page=1
Cookie: session=...
```

**Response — 200**

```json
{"chat_id": "-1001234567890", "public_chat_id": "1234567890", "title": "Movies", "files": [{"id": 42, "title": "Daredevil", "telegram_title": "262838/2/1", "tmdb_title": "Daredevil", "tmdb_id": 262838, "tmdb_type": "tv", "season": 2, "episode": 1, "poster_url": "https://image.tmdb.org/t/p/w500/poster.jpg", "stream_url": "/1234567890/stream?id=42&hash=abcdef", "watch_url": "/watch/1234567890?id=42&hash=abcdef"}], "is_admin": false}
```

Each item in `files` follows the File object; the compact example only shows mapping-relevant fields.

### `GET /search/{chat_id}?q={query}&page=1` — User

**Request**

```http
GET /search/1234567890?q=daredevil&page=1
Cookie: session=...
```

**Response — 200**

```json
{"chat_id": "-1001234567890", "public_chat_id": "1234567890", "query": "daredevil", "message": "Movies - daredevil", "files": [{"id": 42, "title": "Daredevil", "telegram_title": "Daredevil S02E01 1080p", "tmdb_title": "Daredevil", "tmdb_id": 262838, "tmdb_type": "tv", "season": null, "episode": null}], "is_admin": false}
```

### `GET /playlist?db={folder_id}&page=1` — User

**Request**

```http
GET /playlist?db=66abc...&page=1
Cookie: session=...
```

**Response — 200**

```json
{"parent_id": "66abc...", "message": "Favorites", "playlists": [{"id": "66def...", "title": "Series", "name": "Series", "type": "folder", "thumbnail": null, "parent_folder": "66abc...", "url": "/playlist?db=66def..."}], "files": [{"id": "670...", "file_id": "42", "chat_id": "-1001234567890", "public_chat_id": "1234567890", "title": "Daredevil", "name": "Daredevil", "telegram_title": "Daredevil S02E01 1080p", "tmdb_title": "Daredevil", "tmdb_id": 262838, "tmdb_type": "tv", "season": 2, "episode": 1, "type": "file"}], "is_admin": false}
```

### `GET /search/db/{parent}?q={query}&page=1` — User

**Request**

```http
GET /search/db/66abc...?q=daredevil&page=1
Cookie: session=...
```

**Response — 200**

```json
{"parent_id": "66abc...", "query": "daredevil", "message": "Favorites - daredevil", "files": [{"id": "670...", "title": "Daredevil", "telegram_title": "Daredevil S02E01 1080p", "tmdb_title": "Daredevil", "tmdb_id": 262838, "tmdb_type": "tv"}], "is_admin": false}
```

## File delivery

### `GET /watch/{chat_id}?id={message_id}&hash={hash}` — User

**Request**

```http
GET /watch/1234567890?id=42&hash=abcdef
Cookie: session=...
```

**Response — 200**

```json
{"chat_id": "-1001234567890", "public_chat_id": "1234567890", "file_id": "42", "hash": "abcdef", "stream_url": "/1234567890/stream?id=42&hash=abcdef"}
```

### `GET /api/thumb/{chat_id}?id={message_id}` — public

**Request**

```http
GET /api/thumb/-1001234567890?id=42
```

**Response — 200 (binary, not JSON)**

```json
{"content_type": "image/jpeg", "body": "<JPEG bytes>"}
```

Omit `id` to request the channel image.

### `GET /{chat_id}/{encoded_name}?id={message_id}&hash={hash}` — public

**Request**

```http
GET /1234567890/daredevil.mp4?id=42&hash=abcdef
Range: bytes=0-1048575
```

**Response — 206 (binary, not JSON)**

```json
{"content_type": "video/mp4", "content_range": "bytes 0-1048575/734003200", "content_length": 1048576, "content_disposition": "attachment; filename=\"daredevil.mp4\"", "accept_ranges": "bytes", "body": "<media bytes>"}
```

The JSON is a header/body map for frontend design only; the actual response body is media bytes. A full request is `200`; invalid hashes are `403`, missing files are `404`, and invalid ranges are `416`.

## Admin and management

### `POST /create` — Admin

**Request (form data)**

```http
POST /create
Content-Type: application/x-www-form-urlencoded

folderName=Series&thumbnail=https%3A%2F%2Fexample.com%2Fseries.jpg&parent_dir=db%3D66abc...
```

**Response — 200**

```json
{"created": true, "parent_folder": "66abc..."}
```

### `POST /delete` — Admin

**Request (JSON)**

```json
{"delete_id": "66def...", "parent": "66abc..."}
```

**Response — 200**

```json
{"deleted": true, "parent_folder": "66abc..."}
```

### `POST /edit` — Admin

**Request (form data)**

```http
folder_id=66def...&folderName=Films&thumbnail=https%3A%2F%2Fexample.com%2Ffilms.jpg&parent=66abc...
```

**Response — 200**

```json
{"updated": true, "parent_folder": "66abc..."}
```

### `POST /edit_post` — Admin

**Request (form data)**

```http
file_id=670...&fileName=Daredevil&filethumbnail=https%3A%2F%2Fexample.com%2Fposter.jpg&file_folder_id=66abc...
```

**Response — 200**

```json
{"updated": true, "parent_folder": "66abc..."}
```

### `GET /searchDbFol?query={query}` — Admin

**Request**

```http
GET /searchDbFol?query=series
Cookie: session=...
```

**Response — 200**

```json
[{"_id": "66def...", "name": "Series"}]
```

### `POST /send` — currently public

`selectedIds` is a comma-separated list of `file_id|hash|filename|size|file_type|thumbnail` entries. Do not expose this route to untrusted users.

**Request (form data)**

```http
chatId=1234567890&folderId=66abc...&selectedIds=42%7Cabcdef%7CDaredevil.mp4%7C734.00MB%7Cvideo%2Fmp4%7Chttps%3A%2F%2Fexample.com%2Fposter.jpg
```

**Response — 200**

```json
{"created": 1, "parent_folder": "66abc..."}
```

### `GET /reload?chatId={chat_id|home}` — Admin

**Request**

```http
GET /reload?chatId=1234567890
Cookie: session=...
```

**Response — 200**

```json
{"reloaded": "1234567890"}
```

Use `chatId=home` to clear all cached channel pages; its response is `{"reloaded":"home"}`.

### `POST /config` — Admin

**Request (form data)**

```http
channel=-1001234567890%2C-1009876543210&theme=vapor
```

**Response — 200**

```json
{"updated": true}
```
