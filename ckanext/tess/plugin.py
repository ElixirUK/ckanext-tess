'''plugin.py

'''
import json as json
import ckan.plugins.toolkit as toolkit
import ckan.plugins as plugins
import ckan.lib.helpers as h
import os
import operator
import urllib2
import urllib
from ckan.common import OrderedDict, c, g, request, _
from ckan.lib.plugins import DefaultGroupForm
import xml.etree.ElementTree as et
import pylons.config as configuration

from dateutil import parser
import datetime
from datetime import timedelta
import ckan.lib.formatters as formatters
from time import gmtime, strftime
from ckanext.tessrelations.model.tables import TessMaterialNode, TessMaterialEvent, TessEvents, TessGroup, TessDomainObject, TessDataset

def get_tess_version():
    '''Return the value of 'version' parameter from the setyp.py config file.
    :rtype: string

        '''
    return configuration.get('ckanext.tess.version', 'N/A')

# Return the iann specific news. This could be replaced with a general news function taking
# the news source as an argument.
def iann_news():
  try:
    with open ("/tmp/iann.txt", "r") as myfile:
      data = myfile.read()
  except Exception, e:
    print "iann_news: " + str(e)
    data = "<p>No events found!</p>"
  return plugins.toolkit.literal(data)


def get_filters_for(field_name):
    try:
        #TODO; Only load 10 filters unless parameter _provider_limit=1000 - provider_limit is calling solr # filters times. Need to minimize
        if not c.active_filters.get(field_name, None): # Don't bother if the filter is already active
            url = construct_url('http://iann.pro/solr/select?facet=true&facet.field=%s&rows=0' % field_name)
            res = urllib2.urlopen(url)
            res = res.read()
            doc = et.fromstring(res)
            fields = doc.findall("./lst/lst/lst/int")
            field_list = []
            for field in fields:
                if field.text != '0' and field.attrib['name']:
                    if field_name == 'provider':
                        name = proper_name(field_name, field.attrib['name'])
                    else:
                        name = field.attrib['name'].title()
                    hash_val = {'name': name, 'count': field.text}
                    field_list.append(hash_val)
            return field_list
        else:
            return [{'name': field_name}, {'count': 0}]
    except Exception, e:
        print 'Could not load country filters \n %s' % e
        return []

# Bit of a hack here - Because providers have acronyms/funny mixtures of cases - we query each provider
# asking for 1 result back, parsing it and using that value as the filter name.
def proper_name(field, name):
    try:
        url = ('http://iann.pro/solr/select?q=%s:%s&rows=1' % (field, urllib.quote(name)))
        res = urllib2.urlopen(url)
        doc = et.fromstring(res.read())
        docs = doc.findall('*/doc')
        provider_name = name.title()
        for doc in docs:
            if doc.find("*/[@name='provider']").text:
                provider_name = doc.find("*/[@name='provider']").text
        return provider_name
    except Exception, e:
        print 'Error loading the correct provider names \n %s' % e
        return name

#def country_filters():

    # For list of ELIXIR countries:
    #here = os.path.dirname(__file__)
    # json file containing country code -> country name map for member and observer countries
    #file = os.path.join(here,'countries-elixir-flat.json')
    #with open(file) as data_file:
    #    try:
    #        # For list of ELIXIR countries:
    #        # countries_map = json.load(data_file)
    #    except Exception, e:
    #        print e
    #        countries_map = []
    #return countries_map


def parse_xml(xml):
    doc = et.fromstring(xml)
    result_element = doc.find('result')
    count = 0
    try:
        count = int(result_element.attrib.get('numFound'))
    except Exception, e:
        print 'Could not load result element'

    docs = doc.findall('*/doc')
    results = []
    for doc in docs:
        start_time = parser.parse(doc.find("*/[@name='start']").text)
        finish_time = parser.parse(doc.find("*/[@name='end']").text)
        start_time = start_time.replace(tzinfo=None)
        finish_time = finish_time.replace(tzinfo=None)

        expired = False
        if datetime.datetime.now() > finish_time:
            expired = formatters.localised_nice_date(finish_time)
        duration = (finish_time - start_time) + timedelta(days=1)



        res = {'title': doc.find("*/[@name='title']").text,
               'provider': doc.find("*/[@name='provider']").text,
               'id': doc.find("*/[@name='id']").text,
               'link': doc.find("*/[@name='link']").text,
               'subtitle': doc.find("*/[@name='subtitle']").text,
               'venue': doc.find("*/[@name='venue']").text,
               'country': doc.find("*/[@name='country']").text,
               'city': doc.find("*/[@name='city']").text,
               'starts': formatters.localised_nice_date(start_time, show_date=True),#, with_hours=True),
               'ends': formatters.localised_nice_date(finish_time, show_date=True),#, with_hours=True), - Most of these are 00:00
               'expired': expired,
               'duration': duration
               #'start': strptime(doc.find("*/[@name='start']", '%Y-%m-%dT%h-%m-%sZ').text)
               }
        results.append(res)
    return {'count': count, 'events': results}


def construct_url(original_url):
    try:
        if c.sort:
            attr, dir = c.sort.split(' ') # e.g end asc or title asc
            original_url = ('%s&sort=%s%%20%s' % (original_url, attr, dir))

        if c.page:
            original_url = ('%s&start=%s' % (original_url, str(c.page*c.rows-c.rows)))
        if c.category:
            original_url = ('%s&q=category:%s' % (original_url, c.category))
        else:
            original_url = ('%s&q=category:%s' % (original_url, 'event'))
        if not c.include_expired_events:  # Exclude this for past events too
            today = strftime("%Y-%m-%dT%H:%M:%SZ", gmtime())
            date = ('start:[%s%%20TO%%20*]' % today)
            original_url = ('%s%%20AND%%20%s' % (original_url, date))
        if c.country:
            original_url = ('%s%%20AND%%20country:"%s"' % (original_url, urllib.quote(c.country)))
        if c.topic:
            original_url = ('%s%%20AND%%20field:"%s"' % (original_url, urllib.quote(c.topic)))
        if c.provider:
            original_url = ('%s%%20AND%%20provider:"%s"' % (original_url, urllib.quote(c.provider)))
        #print original_url
        if c.q:
            split = c.q.replace('-', '","')
            split = split.replace(' ', '","')
            parameters = ('text:("%s","%s")' % (urllib.quote(c.q), split))
            url = ("%s%%20AND%%20%s" % (original_url, urllib.quote(parameters)))
        else:
            url = original_url
        return url
    except Exception, e:
        print 'Failed to construct URL for iAnn API \n %s' % e


def events():
    results = {}
    original_url = 'http://iann.pro/solr/select/?&rows=%s' % c.rows
    url = construct_url(original_url)
    try:
        res = urllib2.urlopen(url)
        res = res.read()
        results = parse_xml(res)
        results['url'] = url
    except Exception, e:
        print 'Error loading events from iANN.pro: \n %s' % e
    return results


def related_events(model):
    try:
        name = model.get('title', None)
        return events(name)
    except Exception, e:
        print 'Model has no title attribute: \n %s' % e
        return None

def has_more_options(options):
    return len(options) > 10


######################
# Plugin starts here #
######################
class TeSSPlugin(plugins.SingletonPlugin, toolkit.DefaultDatasetForm):
    '''TeSS CKAN plugin.

    '''
    # Declare that this class implements IConfigurer.
    #plugins.implements(plugins.IConfigurer)

    plugins.implements(plugins.IConfigurer, inherit=True)
    plugins.implements(plugins.IRoutes, inherit=True)
    plugins.implements(plugins.IDatasetForm, inherit=True)
    plugins.implements(plugins.ITemplateHelpers, inherit=True)
    plugins.implements(plugins.IFacets, inherit=True)

    def update_config(self, config):
        # Add this plugin's templates dir to CKAN's extra_template_paths, so
        # that CKAN will use this plugin's custom templates.
        # 'templates' is the path to the templates dir, relative to this
        # plugin.py file.
        toolkit.add_template_directory(config, 'templates')
        toolkit.add_public_directory(config, 'public')
        toolkit.add_resource('fantastic', 'tess')

        # set the title
        config['ckan.site_title'] = "TeSS Training Portal"

        # set the logo
        config['ckan.site_logo'] = 'images/ELIXIR_TeSS_logo_white-small.png'

        config['ckanext.tess.version'] = '0.9.1-alpha'

        #config['ckan.template_head_end'] = config.get('ckan.template_head_end', '') +\
        #                '<link rel="stylesheet" href="/css/tess.css" type="text/css"> '

    def before_map(self, map):
        map.connect('node_old', '/node_old', controller='ckanext.tess.plugin:TeSSController', action='node_old')
        map.connect('associate_event', '/event/associate/{id}', controller='ckanext.tess.plugin:TeSSController', action='associate_event')
        map.connect('event', '/event', controller='ckanext.tess.plugin:TeSSController', action='events')
        map.connect('dataset_events', '/dataset/events/{id}', controller='ckanext.tess.plugin:TeSSController', action='add_events', ckan_icon='calendar')
        map.connect('report_event', '/event/new', controller='ckanext.tess.plugin:TeSSController', action='report_event')
        return map

    def dataset_facets(self, facets_dict, package_type):
        facets_dict['node_id'] = 'ELIXIR Nodes'
        return facets_dict

    def setup_template_variables(self, context, data_dict):
        c.filterable_nodes = 'HI'


    def get_helpers(self):
        return {
                'get_tess_version' : get_tess_version,
                'has_more_options': has_more_options,
                'read_news_iann': iann_news,
                'related_events': related_events,
                'events': events
                }

    def _modify_package_schema(self, schema):
        schema.update({
            'node_id': [
                toolkit.get_validator('ignore_missing'),
                toolkit.get_converter('convert_to_extras')]
        })
        return schema

    def show_package_schema(self):
        schema = super(TeSSPlugin, self).show_package_schema()
        schema['tags']['__extras'].append(toolkit.get_converter('free_tags_only'))
        schema.update({
            'node_id': [
                toolkit.get_converter('convert_from_extras'),
                toolkit.get_validator('ignore_missing')]
        })
        return schema

    def create_package_schema(self):
        schema = super(TeSSPlugin, self).create_package_schema()
        schema = self._modify_package_schema(schema)
        return schema

    def update_package_schema(self):
        schema = super(TeSSPlugin, self).update_package_schema()
        schema = self._modify_package_schema(schema)
        return schema

    def is_fallback(self):
        # Return True to register this plugin as the default handler for
        # package types not handled by any other IDatasetForm plugin.
        return True

    def package_types(self):
        # This plugin doesn't handle any special package types, it just
        # registers itself as the default (above).
        return []


import ckan.lib.base as base
from ckan.controllers.home import HomeController
import ckan.model as model
import ckan.logic as logic
from urllib import urlencode

get_action = logic.get_action


def pager_url(q=None, page=None):
    params = list([(k, v) for k, v in request.params.items()
                         if k != 'page'])
    params.append(('page', page))
    url = h.url_for(controller='ckanext.tess.plugin:TeSSController', action='events')
    url = url + u'?' + urlencode(params)
    return url


def setup_events():
    q_params = {}
    print request.url
    c.q = q_params['q'] = c.q = request.params.get('q', '')
    c.category = q_params['category'] = request.params.get('category', '')
    c.country = q_params['country'] = request.params.get('country', '')
    c.topic = q_params['topic'] = request.params.get('topic', '')
    c.provider = q_params['provider'] = request.params.get('provider', '')
    c.rows = q_params['rows'] = request.params.get('rows', 25)
    c.sort_by_selected = q_params['sort'] = request.params.get('sort', '')
    c.page_number = q_params['page'] = int(request.params.get('page', 0))
    c.include_expired_events = q_params['include_expired'] = request.params.get('include_expired', False)
    events_hash = events()
    c.active_filters = {'category': c.category, 'topic': c.topic, 'country': c.country, 'provider': c.provider}
    filters = {}
    if not c.filters:
        filters['category'] = get_filters_for('category')
        filters['topic'] = get_filters_for('field')
        filters['provider'] = get_filters_for('provider')
        filters['country'] = get_filters_for('country')
    c.filters = filters

    c.events = events_hash.get('events', None)
    c.events_count = events_hash.get('count', None)
    c.events_url = events_hash.get('url', None)
    c.page = h.Page(
        collection=c.events,
        page=c.page_number,
        url=pager_url,
        item_count=c.events_count,
        items_per_page=c.rows
    )


def get_event_association(material_id, event_id):
    event = model.Session.query(TessMaterialEvent).\
            filter(TessMaterialEvent.material_id == material_id).\
            filter(TessMaterialEvent.event_id == event_id)
    return event.first()

def delete_event_associate(id):
    delete = model.Session.query(TessMaterialEvent).\
        filter(TessMaterialEvent.id == id).first()
    print delete
    return delete


def get_associated_events(material_id):
    events = model.Session.query(TessMaterialEvent).filter(TessMaterialEvent.material_id == material_id)
    results = []
    for event in events.all():
        try:
            results.append(get_event_by_id(event.event_id))
        except Exception:
            print 'Failed to find Event with ID: %s' % event.event_id
    return results


class TeSSController(HomeController):
    def node_old(self):
        return base.render('node_old/index.html')

    def events(self):
        setup_events()
        return base.render('event/read.html')

    def report_event(self):
        # Bit pointless having a link to here to redirect externally; but we can track that as a statistic
        return base.redirect('http://iann.pro/report-event')

    def add_events(self, id):
        context = {'model': model, 'session': model.Session,
                   'api_version': 3, 'for_edit': True,
                   'user': c.user or c.author, 'auth_user_obj': c.userobj}
        pkg_dict = get_action('package_show')(context, {'id': id})
        c.pkg_dict = pkg_dict
        params = {}
        params['q'] = pkg_dict.get('title')

        c.associated_events = get_associated_events(c.pkg_dict.get('id'))
        c.suggested_events = events()
        setup_events()
        return base.render('package/related_events.html')

def get_event_by_id(id):
    url = 'http://iann.pro/solr/select/?q=id:' + id
    print url
    try:
        res = urllib2.urlopen(url)
        res = res.read()
        results = parse_xml(res)
        results['url'] = url
        if results['count'] == 1:
            return results['events'][0]
        else:
            return {}
    except Exception, e:
        print 'Error finding event in iANN.pro: \n %s' % e
        return {}

def save_event(event_dict=None):
    db_event = TessEvents()
    db_event.id = event_dict.get('id')
    db_event.title = event_dict.get('title', '')
    db_event.provider = event_dict.get('provider', '')
    db_event.link = event_dict.get('link', '')
    db_event.subtitle = event_dict.get('subtitle', '')
    db_event.venue = event_dict.get('venue', '')
    db_event.country = event_dict.get('country', '')
    db_event.city = event_dict.get('city', '')
    db_event.starts = event_dict.get('starts', '')
    db_event.ends = event_dict.get('ends', '')
    db_event.duration = event_dict.get('duration', '')
    db_event.save()
    return db_event

def associate_event(context, data_dict):
    print str(request.body)
    print context.get('model').Group
    print data_dict
    # Save the event
    #event = get_event_by_id(data_dict.get('event_id'))
    #save_event(event)

    #Associate the event
    if get_event_association(data_dict.get('resource_id'), data_dict.get('event_id')):
        raise ValidationError('Already Associated. Cannot associate twice!')
    else:
        new_association = TessMaterialEvent()
        new_association.material_id = data_dict.get('resource_id')
        new_association.event_id = data_dict.get('event_id')
        new_association.save()
        return 'Associated successfully'

NotFound = logic.NotFound
ValidationError = logic.ValidationError

def unassociate_event(context, data_dict):
    event = get_event_association(data_dict.get('resource_id'), data_dict.get('event_id'))
    if event:
        event.delete()
        event.commit()
        return 'Unassociated'
    else:
        raise NotFound('Could not find association')

def associated_events(context, data_dict):
    resources = get_associated_events(data_dict.get('resource_id'))
    return resources

class EventsAPI(plugins.SingletonPlugin):
    plugins.implements(plugins.interfaces.IActions)

    def get_actions(self):
        return {
            'associate_event': associate_event,
            'unassociate_event': unassociate_event,
            'associated_events': associated_events
        }