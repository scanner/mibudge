from django.http import HttpResponse
from django.shortcuts import render


####################################################################
#
def index(request):
    """
    Keyword Arguments:
    request --
    """
    return HttpResponse("Hello, world. Money Pools index.")
