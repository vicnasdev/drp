"""
core/views/mobile_blueprint.py

Staff-only interactive mobile app blueprint viewer.
Shows all screens, API endpoints, and wires for the FlutterFlow app.
"""

from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render


@staff_member_required
def mobile_blueprint(request):
    return render(request, 'mobile_blueprint.html')