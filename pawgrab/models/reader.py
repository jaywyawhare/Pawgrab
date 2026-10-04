"""Models for the structured readers: /v1/transcript, /v1/feed, and the /v1/read router."""

from pydantic import BaseModel, Field

from .common import OutputFormat
from .scrape import ScrapeResponse


class TranscriptRequest(BaseModel):
    url: str = Field(..., max_length=2048, description="YouTube video URL (watch, shorts, embed, or youtu.be)")
    languages: list[str] | None = Field(default=None, max_length=10, description="Preferred caption language codes in priority order, e.g. ['en','es']")


class TranscriptSegment(BaseModel):
    start: float
    duration: float
    text: str


class TranscriptResponse(BaseModel):
    success: bool
    video_id: str | None = None
    title: str | None = None
    language: str | None = None
    auto_generated: bool | None = None
    segments: list[TranscriptSegment] | None = None
    text: str | None = None
    error: str | None = None


class FeedRequest(BaseModel):
    url: str = Field(..., max_length=2048, description="RSS 2.0 or Atom feed URL")
    limit: int = Field(default=50, ge=1, le=500, description="Maximum number of items to return")


class FeedItem(BaseModel):
    title: str | None = None
    link: str | None = None
    published: str | None = None
    summary: str | None = None
    id: str | None = None
    author: str | None = None


class FeedResponse(BaseModel):
    success: bool
    type: str | None = None
    title: str | None = None
    link: str | None = None
    description: str | None = None
    items: list[FeedItem] | None = None
    count: int | None = None
    error: str | None = None


class RedditRequest(BaseModel):
    url: str = Field(..., max_length=2048, description="Reddit post, subreddit, or listing URL")
    limit: int = Field(default=50, ge=1, le=100, description="Maximum posts to return for a listing URL")


class RedditPost(BaseModel):
    id: str | None = None
    title: str | None = None
    author: str | None = None
    subreddit: str | None = None
    selftext: str | None = None
    url: str | None = None
    permalink: str | None = None
    score: int | None = None
    upvote_ratio: float | None = None
    num_comments: int | None = None
    created_utc: float | None = None
    flair: str | None = None
    over_18: bool | None = None


class RedditComment(BaseModel):
    author: str | None = None
    body: str | None = None
    score: int | None = None
    created_utc: float | None = None
    replies: list["RedditComment"] = []


class RedditResponse(BaseModel):
    success: bool
    kind: str | None = Field(default=None, description="post (with comments) or listing (posts)")
    post: RedditPost | None = None
    comments: list[RedditComment] | None = None
    posts: list[RedditPost] | None = None
    error: str | None = None


class GithubRequest(BaseModel):
    url: str = Field(..., max_length=2048, description="GitHub repository URL (github.com/owner/repo)")


class GithubResponse(BaseModel):
    success: bool
    full_name: str | None = None
    description: str | None = None
    owner: str | None = None
    owner_type: str | None = None
    url: str | None = None
    homepage: str | None = None
    language: str | None = None
    topics: list[str] | None = None
    stars: int | None = None
    forks: int | None = None
    watchers: int | None = None
    open_issues: int | None = None
    license: str | None = None
    default_branch: str | None = None
    archived: bool | None = None
    created_at: str | None = None
    updated_at: str | None = None
    pushed_at: str | None = None
    error: str | None = None


class ReadRequest(BaseModel):
    url: str = Field(..., max_length=2048, description="Any URL; routed to the transcript, feed, or scrape reader automatically")
    languages: list[str] | None = Field(default=None, max_length=10, description="Preferred caption languages when the URL is a video")
    limit: int = Field(default=50, ge=1, le=500, description="Maximum feed items when the URL is a feed")
    formats: list[OutputFormat] = Field(default=[OutputFormat.MARKDOWN], description="Output formats when the URL falls back to a web scrape")


class ReadResponse(BaseModel):
    success: bool
    kind: str = Field(description="Which reader handled the URL: youtube, reddit, github, feed, or web")
    url: str
    transcript: TranscriptResponse | None = None
    reddit: RedditResponse | None = None
    github: GithubResponse | None = None
    feed: FeedResponse | None = None
    scrape: ScrapeResponse | None = None
    error: str | None = None
