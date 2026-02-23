from django.shortcuts import render


def use_cases_view(request):
    return render(request, 'use_cases.html')
