"""Repository for Article (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.articles import Article
from app.models.blogs import Blog
from app.search import hooks as _search_hooks


class ArticleRepository(_crud_base.Repository[Article]):
    model = Article
    soft_delete = True
    filterable = ("handle", "published")
    sortable = ("created_at", "published_at")
    searchable = ("author", "title")
    eager = ()
    references = {"blog_id": Blog}
    many_to_many = {}


# Keeps the external search index in step (no-op with SEARCH_BACKEND=fts).
ArticleRepository.hooks = _search_hooks.attach(
    "Article", ("author", "title"), ArticleRepository.hooks
)
