import json
import functools
from collections import Iterable

from django.http import HttpResponse


class to_json(object):
    """
    Wrap view functions to render python native and custom 
    objects to json

    >>> from django.test.client import RequestFactory
    >>> requests = RequestFactory()

    Simple wrap returning data into json

    >>> @to_json('plain')
    ... def hello(request):
    ...    return dict(hello='world')

    >>> resp = hello(requests.get('/hello/'))
    >>> print resp.status_code
    200
    >>> print resp.content
    {"hello": "world"}
    
    Result can be wraped in some api manier

    >>> @to_json('api')
    ... def goodbye(request):
    ...    return dict(good='bye')
    >>> resp = goodbye(requests.get('/goodbye', {'debug': 1}))
    >>> print resp.status_code
    200
    >>> print resp.content
    {
        "data": {
            "good": "bye"
        }, 
        "err": 0
    }

    Automaticaly error handling

    >>> @to_json('api')
    ... def error(request):
    ...    raise Exception('Wooot!??')

    >>> resp = error(requests.get('/error', {'debug': 1}))
    >>> print resp.status_code
    500
    >>> print resp.content # doctest: +NORMALIZE_WHITESPACE
    {            
        "err_class": "Exception",
        "err_desc": "Wooot!??",
        "data": null,
        "err": 1
    }

    You can serialize not only pure python data types.
    Implement `serialize` method on toplevel object or 
    each element of toplevel array.

    >>> class User(object):
    ...     def __init__(self, name, age):
    ...         self.name = name
    ...         self.age = age
    ... 
    ...     def serialize(self, request):
    ...         if request.GET.get('with_age', False):
    ...             return dict(name=self.name, age=self.age)
    ...         else:
    ...             return dict(name=self.name)
    
    >>> @to_json('objects')
    ... def users(request):
    ...    return [User('Bob', 10), User('Anna', 12)]

    >>> resp = users(requests.get('users', { 'debug': 1 }))
    >>> print resp.status_code
    200
    >>> print resp.content # doctest: +NORMALIZE_WHITESPACE
    {
        "data": [
            {
                "name": "Bob"
            }, 
            {
                "name": "Anna"
            }
        ], 
        "err": 0
    }

    You can pass extra args for serialization:

    >>> resp = users(requests.get('users', 
    ...     { 'debug':1, 'with_age':1 }))
    >>> print resp.status_code
    200
    >>> print resp.content # doctest: +NORMALIZE_WHITESPACE
    {
        "data": [
            {
                "age": 10, 
                "name": "Bob"
            }, 
            {
                "age": 12, 
                "name": "Anna"
            }
        ], 
        "err": 0
    }

    It is easy to use jsonp, just pass format=jsonp

    >>> resp = users(requests.get('users',
    ...     { 'debug':1, 'format': 'jsonp' }))
    >>> print resp.status_code
    200
    >>> print resp.content # doctest: +NORMALIZE_WHITESPACE
    callback({
        "data": [
            {   
                "name": "Bob"
            },
            {   
                "name": "Anna"
            }
        ],
        "err": 0
    });

    You can override the name of callback method using 
    JSON_RESPONSE_CBNAME option or query arg callback=another_callback
    
    >>> resp = users(requests.get('users',
    ...     { 'debug':1, 'format': 'jsonp', 'callback': 'my_callback' }))
    >>> print resp.status_code
    200
    >>> print resp.content # doctest: +NORMALIZE_WHITESPACE
    my_callback({
        "data": [
            {   
                "name": "Bob"
            },
            {   
                "name": "Anna"
            }
        ],
        "err": 0
    });

    You can pass raise=1 to raise exceptions in debug purposes 
    instead of passing info to json response

    >>> @to_json('api')
    ... def error(request):
    ...    raise Exception('Wooot!??')

    >>> resp = error(requests.get('/error',
    ...     {'debug': 1, 'raise': 1}))
    Traceback (most recent call last):
    Exception: Wooot!??

    """
    def __init__(self, serializer_type):
        """
        serializer_types:
            * api - serialize buildin objects (dict, list, etc) in strict api
            * objects - serialize list of region in strict api
            * plain - just serialize result of function, do not wrap response and do not handle exceptions
        """
        self.serializer_type = serializer_type

    def __call__(self, f):
        if self.serializer_type == 'plain': 
            @functools.wraps(f)
            def wrapper(*args, **kwargs):
                return self.plain(f, *args, **kwargs)
        else:
            @functools.wraps(f)
            def wrapper(*args, **kwargs):
                return self.api(f, *args, **kwargs)

        return wrapper
    
    def obj_to_response(self, req, obj):
        if self.serializer_type == 'objects' and obj:
            if isinstance(obj, Iterable):
                obj = [o.serialize(req) if obj else None for o in obj]
            else:
                obj = obj.serialize(req)
        
        return { "err": 0, "data": obj }

    def err_to_response(self, err):
        if hasattr(err, "__module__"):
            err_module = err.__module__ + "."
        else:
            err_module = ""

        if hasattr(err, "owner"):
            err_module += err.owner.__name__ + "."

        err_class = err_module + err.__class__.__name__

        err_desc = str(err)
        
        return {
            "err": 1,
            "err_class": err_class,
            "err_desc": err_desc,
            "data": None
        }

    def render_data(self, req, data, status=200):
        debug = req.GET.get('debug', 'false').lower() in ('true', 't', '1', 'on')
        debug = debug or req.GET.get('decode', '0').lower() in ('true', 't', '1', 'on')
        format = req.GET.get('format', 'json')
        jsonp_cb = req.GET.get('callback', 'callback')
        content_type = "application/json"
        
        kwargs = {}
        if debug:
            kwargs["indent"] = 4
            kwargs["ensure_ascii"] = False
            kwargs["encoding"] = "utf8"

        plain = json.dumps(data, **kwargs)
        if format == 'jsonp':
            plain = "%s(%s);" % (jsonp_cb, plain)
            content_type = "application/javascript"
        
        return HttpResponse(plain, content_type="%s; charset=UTF-8" % content_type, status=status)
        

    def api(self, f, req, *args, **kwargs):
        try:
            resp = f(req, *args, **kwargs)
            data = self.obj_to_response(req, resp)
            status = 200
        except Exception, e:
            if int(req.GET.get('raise', 0)):
                raise
            data = self.err_to_response(e)
            status = 500

        return self.render_data(req, data, status)

    def plain(self, f, req, *args, **kwargs):
        data = f(req, *args, **kwargs)
        return self.render_data(req, data)

if __name__ == '__main__':
    import doctest
    import os
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", __name__)
    doctest.testmod()