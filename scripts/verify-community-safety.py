"""Run only against the disposable local PostgreSQL QA database, never production."""
import os
if os.environ.get("DATABASE_URL") != "postgresql+asyncpg://postgres:local-qa-only@127.0.0.1:55439/soundscore_qa":
 raise SystemExit("Use the disposable soundscore-release-qa database on port 55439")
import asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from app.main import app
from app.database import AsyncSessionLocal, engine
from app.models.user import User
from app.models.review import Album, Review
from app.core.security import create_access_token
from app.services.cache_service import CacheService

async def main():
 CacheService.get_json = classmethod(lambda cls,*a,**k: asyncio.sleep(0,result=None))
 CacheService.set_json = classmethod(lambda cls,*a,**k: asyncio.sleep(0))
 CacheService.delete_pattern = classmethod(lambda cls,*a,**k: asyncio.sleep(0,result=0))
 async with engine.begin() as conn:
  await conn.run_sync(__import__('app.database',fromlist=['Base']).Base.metadata.create_all)
 async with AsyncSessionLocal() as db:
  await db.execute(__import__('sqlalchemy').text('TRUNCATE users, albums RESTART IDENTITY CASCADE'))
  alice=User(username='qa_alice',email='alice@example.com',is_active=True)
  bob=User(username='qa_bob',email='bob@example.com',is_active=True)
  admin=User(username='qa_admin',email='admin@example.com',is_active=True,is_superuser=True)
  db.add_all([alice,bob,admin]);await db.flush()
  album=Album(spotify_id='qa-album',title='QA album',artist='QA artist');db.add(album);await db.flush()
  review=Review(user_id=bob.id,album_id=album.id,rating=4,text='QA review');db.add(review);await db.commit()
  ids=(alice.id,bob.id,admin.id);review_uuid=str(review.uuid)
 def headers(user,i):return {'Authorization':'Bearer '+create_access_token(user,user_id=i)}
 ah,bh,mh=headers('qa_alice',ids[0]),headers('qa_bob',ids[1]),headers('qa_admin',ids[2])
 async with AsyncClient(transport=ASGITransport(app=app),base_url='http://qa') as c:
  async def req(method,path,h,expected,**kw):
   r=await c.request(method,'/api/v1'+path,headers=h,**kw)
   assert r.status_code==expected,(path,r.status_code,r.text)
   return r.json()
  status=await req('GET','/moderation/terms',ah,200);assert not status['accepted']
  await req('POST','/reviews',ah,403,json={'spotify_id':'qa-album','title':'QA album','artist':'QA artist','rating':5,'text':'test'})
  await req('POST','/moderation/terms',ah,200,json={'version':'2026-10-03'})
  await req('POST','/moderation/terms',ah,200,json={'version':'2026-10-03'})
  status=await req('GET','/moderation/terms',ah,200);assert status['accepted']
  conv=await req('POST','/dm/conversations/qa_bob',ah,200)
  await req('POST','/moderation/reports',ah,201,json={'target_type':'review','target_id':review_uuid,'reason':'spam'})
  await req('POST','/moderation/reports',ah,201,json={'target_type':'review','target_id':review_uuid,'reason':'spam'})
  await req('GET','/moderation/reports',ah,403)
  reports=await req('GET','/moderation/reports',mh,200);assert len(reports['reports'])==1
  await req('PUT','/moderation/blocks/qa_bob',ah,200)
  await req('PUT','/moderation/blocks/qa_bob',ah,200)
  await req('POST','/dm/conversations/qa_bob',ah,403)
  await req('POST','/dm/conversations/qa_alice',bh,403)
  await req('POST',f"/dm/conversations/{conv['id']}/messages",ah,403,json={'content':'blocked'})
  await req('GET',f"/dm/conversations/{conv['id']}/messages",bh,403)
  feed=await req('GET','/feed',ah,200);assert not feed['reviews']
  await req('GET',f'/reviews/{review_uuid}',ah,403)
  blocks=await req('GET','/moderation/blocks',ah,200);assert len(blocks['users'])==1
  await req('DELETE','/moderation/blocks/qa_bob',ah,200)
  await req('POST',f"/dm/conversations/{conv['id']}/messages",ah,201,json={'content':'allowed'})
  await req('POST',f"/moderation/reports/{reports['reports'][0]['id']}/resolve",mh,200,json={'action':'remove','note':'Confirmed spam'})
  await req('GET',f'/reviews/{review_uuid}',ah,404)
  await req('DELETE','/users/account',ah,200)
  print('PASS: 25 API checks covering terms, report deduplication, moderator permissions, bilateral blocks, feed visibility, removal and account deletion')
 await engine.dispose()
asyncio.run(main())
