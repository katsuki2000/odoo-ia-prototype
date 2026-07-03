{
    'name' : "Estate",
    'version': '1.0',
    'depends': ['base', 'mail'],
    'author':"Mr Rai",
    'category':'App',
    'description':"""
        This module is used to learn basic Odoo 17 technical
        """,
    'application':True,
    'sequence': -10,
    'data':[
        #security
        'security/ir.model.access.csv',
        #templates
        'data/templates/example_email_template.xml',    
        #views
        'views/estate_property_views.xml',
        'views/estate_property_type.xml',
        'views/menu.xml', #the order of the menu is important, because the menu is created in the order of the views, so if you want to create a menu that is a child of another menu, you need to create the parent menu first.
        #LOAD INITIAL DATA
        'data/estate.property.csv',

        #schedulers
        'views/schedulers/estate_property_scheduler.xml'

    ],

}