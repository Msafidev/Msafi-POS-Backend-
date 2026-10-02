import csv
from datetime import date, timedelta

from django.http import HttpResponse
from django.utils import timezone


def parse_date_range(request):
    """
    Every report accepts ?start=YYYY-MM-DD&end=YYYY-MM-DD and defaults to
    the current calendar month when omitted — matches the brief's Daily/
    Weekly/Monthly/Yearly report framing while keeping one shared code path.
    """
    today = timezone.localdate()
    start_str = request.query_params.get("start")
    end_str = request.query_params.get("end")
    try:
        start = date.fromisoformat(start_str) if start_str else today.replace(day=1)
    except ValueError:
        start = today.replace(day=1)
    try:
        end = date.fromisoformat(end_str) if end_str else today
    except ValueError:
        end = today
    return start, end


def as_csv(filename, fieldnames, rows):
    """rows: iterable of dicts matching fieldnames."""
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    writer = csv.DictWriter(response, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return response


def wants_csv(request):
    return request.query_params.get("export") == "csv"
