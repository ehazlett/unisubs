from django.db import models
from auth.models import CustomUser as User

class AuthMeta(models.Model):
    """Metadata for Authentication"""
    def __unicode__(self):
        return '%s - %s' % (self.user, self.provider)
    
    user = models.OneToOneField(User)
    provider = models.CharField(max_length = 30)
    is_email_filled = models.BooleanField(default = False)
    is_profile_modified = models.BooleanField(default = False)

class OpenidProfile(models.Model):
    """A class associating an User to a Openid"""
    openid_key = models.CharField(max_length=200,unique=True)
    
    user = models.ForeignKey(User)
    is_username_valid = models.BooleanField(default = False)
    #Values which we get from openid.sreg
    email = models.EmailField()
    nickname = models.CharField(max_length = 100)
    
    
    def __unicode__(self):
        return unicode(self.openid_key)
    
    def __repr__(self):
        return unicode(self.openid_key)
    

