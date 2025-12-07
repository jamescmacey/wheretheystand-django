from .base import BaseModel
from django.db import models
from .documents import File, Licence, CopyrightParty
from django.core.files.base import ContentFile
import urllib.request
import urllib.error
import re
from django.utils import timezone
from bs4 import BeautifulSoup
from datetime import datetime
from django.conf import settings

class GazetteNotice(BaseModel):
    """
    A gazette notice.
    """
    number = models.CharField(max_length=255, unique=True)
    file = models.ForeignKey(File, on_delete=models.SET_NULL, related_name="gazette_notices", null=True, blank=True)

    def __str__(self):
        return self.number

    def save(self, *args, **kwargs):
        # Only download if file doesn't exist and we have a number
        if not self.file and self.number:
            try:
                # Construct the PDF URL - try common patterns
                base_url = f"https://gazette.govt.nz/notice/id/{self.number}"
                pdf_urls = [
                    f"{base_url}/pdf",
                ]
                
                pdf_content = None
                pdf_url = None
                
                # Try each URL pattern
                for url in pdf_urls:
                    try:
                        req = urllib.request.Request(url)
                        req.add_header('User-Agent', settings.BOT_USER_AGENT)
                        with urllib.request.urlopen(req, timeout=30) as response:
                            content_type = response.headers.get('Content-Type', '')
                            # Check if it's a PDF
                            if 'pdf' in content_type.lower() or url.endswith('pdf'):
                                pdf_content = response.read()
                                pdf_url = url
                                break
                    except (urllib.error.HTTPError, urllib.error.URLError) as e:
                        continue

                # Access the base URL and scrape it to get the document description and published date              
                try:
                    base_url_response = urllib.request.urlopen(base_url, timeout=10, headers={'User-Agent': settings.BOT_USER_AGENT})
                    base_url_content = base_url_response.read()
                except (urllib.error.HTTPError, urllib.error.URLError) as e:
                    print(f"Error retrieving Gazette Notice page for {self.number}: {e}")
                    base_url_content = b""
                
                if base_url_content:
                    soup = BeautifulSoup(base_url_content, 'html.parser')

                    # The document description has class "ci-notice-title"
                    notice_title = soup.find('h2', class_='ci-notice-title').get_text()

                    # The published date is the element immediately following a dt element containing the text "Publication Date"
                    published_date = soup.find('dt', text='Publication Date').find_next('dd').get_text()

                    # It is in the format XX Oct 2025
                    published_date = datetime.strptime(published_date.strip().replace(' ', '').replace("\n", ''), '%d%b%Y').date()
                else:
                    notice_title = f"Gazette notice {self.number}"
                    published_date = timezone.now().date()
                


                # If we successfully downloaded the PDF, create a File object
                if pdf_content:
                    try:
                        # Create a temporary file to use with Django's FileField
                        filename = f"{self.number}.pdf"
                        
                        # Create File object (don't save yet)
                        file_obj = File(
                            file_name=notice_title.strip(),
                            file_description=f"Gazette notice {self.number}",
                            original_link_alive=True,
                            original_link_last_checked=timezone.now(),
                            source_url=pdf_url or base_url,
                            file_type="application/pdf",
                            published_date=published_date,
                            licence=Licence.objects.get_or_create(name="Creative Commons Attribution 3.0 New Zealand")[0],
                            copyright_owner=CopyrightParty.objects.get_or_create(name="Crown Copyright")[0],
                            licence_grantor=CopyrightParty.objects.get_or_create(name="Department of Internal Affairs")[0],
                        )
                        
                        # Store the content temporarily so upload_to can access it for hashing
                        file_obj._file_content_for_hash = pdf_content
                        
                        # Save the file content to the FileField
                        # This will trigger the upload_to function and save to storage
                        file_obj.file.save(filename, ContentFile(pdf_content), save=False)
                        
                        # Now save the File object - this will calculate the MD5 hash
                        file_obj.save()
                        
                        # Link the file to this notice
                        self.file = file_obj
                    except Exception as e:
                        # Log the error but don't prevent saving the notice
                        # You might want to add proper logging here
                        print(f"Error creating File object for notice {self.number}: {e}")
            except Exception as e:
                # Log the error but don't prevent saving the notice
                # You might want to add proper logging here
                print(f"Error saving Gazette notice {self.number}: {e}")
        
        super().save(*args, **kwargs)