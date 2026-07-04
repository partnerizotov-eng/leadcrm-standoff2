"""Универсальная пагинация"""
from math import ceil

class Pagination:
    def __init__(self, items, page=1, per_page=20):
        self.items = items
        self.page = page
        self.per_page = per_page
        self.total = len(items)
        self.pages = ceil(self.total / per_page) if self.total > 0 else 1
        self.start = (page - 1) * per_page
        self.end = self.start + per_page
        self.current_items = items[self.start:self.end]
    
    @property
    def has_prev(self):
        return self.page > 1
    
    @property
    def has_next(self):
        return self.page < self.pages
    
    @property
    def prev_num(self):
        return self.page - 1 if self.has_prev else None
    
    @property
    def next_num(self):
        return self.page + 1 if self.has_next else None
    
    def iter_pages(self, left_edge=2, left_current=2, right_current=5, right_edge=2):
        last = 0
        for num in range(1, self.pages + 1):
            if num <= left_edge or \
               (num > self.page - left_current - 1 and num < self.page + right_current) or \
               num > self.pages - right_edge:
                if last + 1 != num:
                    yield None
                yield num
                last = num
