"""Seed data used ONLY when a brand-new database is created.

After the first run the database is the single source of truth: editing this file
never changes an existing installation, and deleted books/periods never come back.
"""

DEFAULT_BOOKS = ("English", "Mathematics", "Science", "Computer Science", "Tamil")

DEFAULT_TIMETABLE = {
    "Monday": ["English", "Mathematics", "Science", "Computer Science", "Tamil"],
    "Tuesday": ["Mathematics", "English", "Computer Science", "Science", "Tamil"],
    "Wednesday": ["Science", "Mathematics", "English", "Tamil", "Computer Science"],
    "Thursday": ["Computer Science", "Science", "Mathematics", "English", "Tamil"],
    "Friday": ["Tamil", "English", "Mathematics", "Science", "Computer Science"],
}
