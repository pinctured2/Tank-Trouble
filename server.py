"""Tank Trouble Arena: small room server for browser multiplayer."""
import asyncio, json, random, string, os, math, socket
from aiohttp import web, WSMsgType

ROOT = __import__('pathlib').Path(__file__).parent
rooms = {}
COLORS = {'red':'#ff555d','blue':'#52a6ff','green':'#55d98b','purple':'#b07bff','orange':'#ff9c4a','yellow':'#f3d65c'}
DROP_ITEMS = ['Boost','Homing missile','Oil slick','Smoke screen','Mine','Rocket','Repair kit','EMP pulse','Shield','Scatter shot']
RACE_ITEMS = ['Homing missile','Boost','Shield','Oil slick','EMP pulse','Smoke screen','Repair kit','Scatter shot']
OBSTACLES = [
    [(210,125,105,28),(390,190,28,115),(570,100,125,26),(750,195,30,115),(290,355,135,28),(520,390,30,95),(690,350,105,28)],
    [(190,130,120,32),(400,120,32,130),(610,190,140,34),(270,360,32,110),(480,370,145,32),(740,350,30,120)],
    [(220,120,120,30),(470,115,30,120),(690,180,130,30),(310,355,30,120),(520,375,135,30),(760,350,30,110)],
    [(185,140,32,125),(330,170,110,30),(555,120,30,140),(700,170,135,32),(260,370,125,30),(485,355,30,120),(680,370,120,30)],
    [(205,120,120,32),(415,185,30,120),(630,120,125,32),(275,375,30,115),(485,365,145,30),(740,350,30,120)],
    [(200,140,115,30),(430,120,30,125),(660,155,125,30),(290,355,30,115),(490,380,125,30),(730,345,30,120)],
    [(180,135,120,35),(395,175,35,120),(620,130,130,35),(265,365,35,115),(480,365,145,35),(750,355,35,115)],
    [(210,125,130,35),(460,105,35,135),(690,180,135,35),(275,365,35,120),(500,375,140,35),(760,355,35,110)],
    [(205,130,115,35),(420,155,35,125),(660,125,130,35),(270,365,35,115),(500,370,130,35),(730,350,35,115)],
    [(170,110,130,32),(375,160,32,125),(620,110,135,32),(285,360,32,125),(500,375,145,32),(770,345,32,120)],
    [(225,125,85,30),(405,205,30,105),(625,135,95,30),(760,270,30,95),(285,375,105,30),(535,365,30,105),(695,405,85,30)]
]
MAPS = ['neon','canyon','ice','jungle','volcano','sakura','toxic','moon','temple','military','halloween']
RACE_TRACKS = {
    'military':{'name':'Operation Checkpoint','points':[(170,280),(267,142),(500,85),(733,142),(830,280),(733,418),(500,475),(267,418)],'effect':'boost','zone':(500,85)},
    'neon':{'name':'Neon Grid','points':[(170,145),(330,105),(630,105),(820,165),(855,365),(720,455),(430,455),(170,380),(135,255)],'effect':'pulse','zone':(630,105)},
    'canyon':{'name':'Dust Devil Switchback','points':[(160,440),(280,355),(230,240),(330,135),(540,110),(700,185),(850,130),(875,280),(760,360),(700,465),(480,445),(370,350),(255,285)],'effect':'sand','zone':(700,185)},
    'ice':{'name':'Polar Figure Eight','points':[(180,280),(240,160),(420,130),(500,280),(580,430),(760,400),(820,280),(760,160),(580,130),(500,280),(420,430),(240,400)],'effect':'drift','zone':(500,280)},
    'jungle':{'name':'Canopy Run','points':[(180,400),(260,200),(400,110),(550,220),(760,125),(830,300),(700,450),(500,390),(340,470)],'effect':'vines','zone':(550,220)},
    'halloween':{'name':'Haunted Hollow','points':[(155,300),(225,155),(365,105),(485,155),(620,100),(790,155),(850,300),(770,425),(610,465),(470,410),(330,465),(190,405),(135,300)],'effect':'haunt','zone':(485,155)}
}

def race_points(map_name):return RACE_TRACKS.get(map_name,RACE_TRACKS['military'])['points']

def race_spawn(map_name,index=0):
    pts=race_points(map_name);a=pts[0];b=pts[1];dx=b[0]-a[0];dy=b[1]-a[1];length=max(1,math.hypot(dx,dy));offset=((index%3)-1)*17
    return {'x':a[0]-(dy/length)*offset,'y':a[1]+(dx/length)*offset,'angle':math.atan2(dy,dx)}

def track_length(points):return sum(math.dist(points[i],points[(i+1)%len(points)]) for i in range(len(points)))

def track_position(map_name,fraction):
    pts=race_points(map_name);length=track_length(pts);distance=(fraction%1)*length
    for i,a in enumerate(pts):
        b=pts[(i+1)%len(pts)];seg=math.dist(a,b)
        if distance<=seg:
            t=distance/max(seg,1);return a[0]+(b[0]-a[0])*t,a[1]+(b[1]-a[1])*t
        distance-=seg
    return pts[0]

async def check_track_effect(room,player):
    st=rooms.get(room)
    if not st or st.get('mode')!='race':return
    track=RACE_TRACKS.get(st.get('map'),RACE_TRACKS['military']);zone=track['zone'];now=asyncio.get_running_loop().time()
    if math.dist((player['x'],player['y']),zone)>38 or now<player.get('trackEffectAt',0):return
    player['trackEffectAt']=now+4
    effect=track['effect'];duration=2500 if effect in ('boost','pulse') else 1800
    if effect in ('boost','pulse'):player['boostUntil']=now+(4 if effect=='pulse' else 2.5)
    elif effect=='sand':player['slowedUntil']=now+2
    elif effect=='drift':player['driftUntil']=now+2.5
    elif effect=='vines':player['stunnedUntil']=now+.65
    elif effect=='haunt':player['stunnedUntil']=now+.55
    await broadcast(room,{'type':'track_effect','target':player['id'],'effect':effect,'duration':duration,'track':track['name']})

def closest_on_segment(point,a,b):
    dx=b[0]-a[0];dy=b[1]-a[1];den=dx*dx+dy*dy
    t=max(0,min(1,((point[0]-a[0])*dx+(point[1]-a[1])*dy)/max(den,1)))
    return (a[0]+dx*t,a[1]+dy*t),t

def track_progress(map_name,x,y):
    pts=race_points(map_name);total=track_length(pts);best=(float('inf'),0)
    before=0
    for i,a in enumerate(pts):
        b=pts[(i+1)%len(pts)];seg=math.dist(a,b);q,t=closest_on_segment((x,y),a,b);d=math.dist((x,y),q)
        if d<best[0]:best=(d,(before+t*seg)/max(total,1))
        before+=seg
    return best[1]

def blocked(map_name, x, y, radius=16):
    index = MAPS.index(map_name) if map_name in MAPS else 0
    return any(x+radius>ox and x-radius<ox+w and y+radius>oy and y-radius<oy+h for ox,oy,w,h in OBSTACLES[index])

def arena_spawn(map_name,players=()):
    occupied=[(p['x'],p['y']) for p in players if p.get('alive',True)]
    for _ in range(500):
        x=random.randint(45,955);y=random.randint(45,515)
        if not blocked(map_name,x,y,19) and all(math.dist((x,y),q)>=46 for q in occupied):return {'x':x,'y':y,'angle':random.random()*math.tau}
    for y in range(48,513,24):
        for x in range(48,953,24):
            if not blocked(map_name,x,y,19) and all(math.dist((x,y),q)>=38 for q in occupied):return {'x':x,'y':y,'angle':0}
    for y in range(48,513,24):
        for x in range(48,953,24):
            if not blocked(map_name,x,y,19):return {'x':x,'y':y,'angle':0}
    raise RuntimeError('No clear tank spawn point is available')
def on_race_track(map_name,x,y):
    return min(math.dist((x,y),closest_on_segment((x,y),race_points(map_name)[i],race_points(map_name)[(i+1)%len(race_points(map_name))])[0]) for i in range(len(race_points(map_name))))<32

def clear_shot(map_name,x1,y1,x2,y2):
    steps=max(1,int(math.dist((x1,y1),(x2,y2))/8))
    return not any(blocked(map_name,x1+(x2-x1)*i/steps,y1+(y2-y1)*i/steps,3) for i in range(1,steps))

def race_rank(player,map_name='military'):
    return player.get('lap',0)+track_progress(map_name,player['x'],player['y'])

def race_item_for(state):
    racers=list(state.get('players',{}).values())
    if not racers:return random.choice(RACE_ITEMS)
    map_name=state.get('map','military');ordered=sorted(racers,key=lambda p:race_rank(p,map_name))
    trailing=min(1,max(0,(race_rank(ordered[-1],map_name)-race_rank(ordered[0],map_name))/.75)) if len(ordered)>1 else .5
    if trailing>.65:return random.choices(RACE_ITEMS,[24,12,8,5,14,5,4,14])[0]
    if trailing<.35:return random.choices(RACE_ITEMS,[5,8,12,22,5,18,20,4])[0]
    return random.choice(RACE_ITEMS)

def homing_target(state,shooter):
    racers=[p for p in state['players'].values() if p['id']!=shooter['id'] and p.get('alive',True)]
    if not racers:return None
    if state.get('mode')=='race':
        map_name=state.get('map','military');rank=race_rank(shooter,map_name);ahead=sorted((p for p in racers if race_rank(p,map_name)>rank+.01),key=lambda p:race_rank(p,map_name))
        if ahead:return ahead[0]
        return min(racers,key=lambda p:race_rank(p,state.get('map','military')))
    return min(racers,key=lambda p:(p['x']-shooter['x'])**2+(p['y']-shooter['y'])**2)

def hit_wall(st,x,y):
    if x<24 or x>976 or y<24 or y>536:return True
    if st.get('mode')=='race':return not on_race_track(st.get('map','military'),x,y)
    return blocked(st.get('map','neon'),x,y,4)

async def launch_fireball(room,owner_id):
    st=rooms.get(room);owner=st and st.get('players',{}).get(owner_id)
    if not owner:return
    pid=''.join(random.choices(string.ascii_letters+string.digits,k=9));x=owner['x']+math.cos(owner.get('angle',0))*25;y=owner['y']+math.sin(owner.get('angle',0))*25;angle=owner.get('angle',0)
    await broadcast(room,{'type':'projectile','id':pid,'kind':'Fireball','owner':owner_id,'x':x,'y':y,'angle':angle,'color':'#ff472e'})
    for _ in range(60):
        await asyncio.sleep(.04);st=rooms.get(room)
        if not st:break
        nx=x+math.cos(angle)*13;ny=y+math.sin(angle)*13
        if hit_wall(st,nx,y):break
        if hit_wall(st,x,ny):break
        x=nx;y=ny;await broadcast(room,{'type':'missile','id':pid,'x':x,'y':y,'angle':angle,'speed':13})
        target=next((p for p in st['players'].values() if p['id']!=owner_id and p.get('alive',True) and math.dist((x,y),(p['x'],p['y']))<23),None)
        if target:
            await eliminate(room,target['id'],owner_id,'Fire ability hit '+target['name']+'!',item_hit=True);break
    await broadcast(room,{'type':'missile_done','id':pid})

async def launch_mega_missile(room,owner_id,target_id):
    st=rooms.get(room);owner=st and st.get('players',{}).get(owner_id);target=st and st.get('players',{}).get(target_id)
    if not owner or not target:return
    missile_id=''.join(random.choices(string.ascii_letters+string.digits,k=9));x=owner['x'];y=owner['y'];angle=math.atan2(target['y']-y,target['x']-x);speed=15
    await broadcast(room,{'type':'mega_launch','owner':owner_id,'target':target_id,'name':owner.get('name','Arena AI')})
    await broadcast(room,{'type':'projectile','id':missile_id,'kind':'Mega missile','owner':owner_id,'target':target_id,'x':x,'y':y,'angle':angle,'color':'#ff372e'})
    await broadcast(room,{'type':'missile_warning','target':target_id,'shooter':owner_id,'kind':'Mega missile','duration':10000})
    hit=False
    for _ in range(200):
        await asyncio.sleep(.05);st=rooms.get(room);target=st and st.get('players',{}).get(target_id)
        if not st:break
        if target and target.get('alive',True):
            desired=math.atan2(target['y']-y,target['x']-x);turn=(desired-angle+math.pi)%(2*math.pi)-math.pi;angle+=max(-.12,min(.12,turn))
        dx=math.cos(angle)*speed;dy=math.sin(angle)*speed;hit_x=hit_wall(st,x+dx,y);hit_y=hit_wall(st,x,y+dy)
        if hit_x:dx=-dx
        if hit_y:dy=-dy
        angle=math.atan2(dy,dx)
        if not hit_x:x+=dx
        if not hit_y:y+=dy
        await broadcast(room,{'type':'missile','id':missile_id,'x':x,'y':y,'angle':angle,'speed':speed})
        if target and target.get('alive',True) and math.dist((x,y),(target['x'],target['y']))<30:
            await eliminate(room,target_id,owner_id,'Arena AI mega missile crushed '+target.get('name','the player')+'!',item_hit=True,explosion_scale=1.8)
            if target.get('alive',True):await broadcast(room,{'type':'explosion','x':x,'y':y,'color':'#ff752d','scale':1.8})
            hit=True;break
    if not hit and room in rooms:await broadcast(room,{'type':'explosion','x':x,'y':y,'color':'#ff752d','scale':2.1})
    await broadcast(room,{'type':'missile_done','id':missile_id})

async def launch_earth_rock(room,owner_id,target_id):
    st=rooms.get(room);owner=st and st.get('players',{}).get(owner_id);target=st and st.get('players',{}).get(target_id)
    if not owner or not target:return
    rock_id=''.join(random.choices(string.ascii_letters+string.digits,k=9));angle=owner.get('angle',0);x=owner['x']+math.cos(angle)*38;y=owner['y']+math.sin(angle)*38
    await broadcast(room,{'type':'projectile','id':rock_id,'kind':'Earth rock','owner':owner_id,'target':target_id,'x':x,'y':y,'angle':angle,'color':'#ff8a24'})
    for _ in range(160):
        await asyncio.sleep(.05);st=rooms.get(room);target=st and st.get('players',{}).get(target_id)
        if not st:break
        if target and target.get('alive',True):
            desired=math.atan2(target['y']-y,target['x']-x);turn=(desired-angle+math.pi)%(2*math.pi)-math.pi;angle+=max(-.2,min(.2,turn))
        x+=math.cos(angle)*9;y+=math.sin(angle)*9
        await broadcast(room,{'type':'missile','id':rock_id,'x':x,'y':y,'angle':angle,'speed':9})
        if target and target.get('alive',True) and math.dist((x,y),(target['x'],target['y']))<34:
            await eliminate(room,target_id,owner_id,'Orange earth rock crushed '+target.get('name','a tank')+'!',item_hit=True,explosion_scale=1.6)
            if target.get('alive',True):await broadcast(room,{'type':'explosion','x':x,'y':y,'color':'#ff8a24','scale':1.6})
            break
    await broadcast(room,{'type':'missile_done','id':rock_id})

async def launch_homing(room,attacker_id,target_id,kind='Homing missile'):
    missile_id=''.join(random.choices(string.ascii_letters+string.digits,k=9))
    st=rooms.get(room);attacker=st and st['players'].get(attacker_id)
    if not attacker:return
    x=attacker['x'];y=attacker['y'];angle=attacker.get('angle',0)
    await broadcast(room,{'type':'projectile','id':missile_id,'kind':kind,'owner':attacker_id,'target':target_id,'x':x,'y':y,'angle':angle,'color':'#fff'})
    await broadcast(room,{'type':'missile_warning','target':target_id,'shooter':attacker_id,'duration':4800})
    for _ in range(120):
        await asyncio.sleep(.04);st=rooms.get(room);target=st and st['players'].get(target_id)
        if not target or not target.get('alive',True):break
        angle=math.atan2(target['y']-y,target['x']-x);x+=math.cos(angle)*17;y+=math.sin(angle)*17
        await broadcast(room,{'type':'missile','id':missile_id,'x':x,'y':y,'angle':angle})
        if math.dist((x,y),(target['x'],target['y']))<22:
            await eliminate(room,target_id,attacker_id,'Homing missile locked on and hit '+target['name']+'!',item_hit=True);break
    await broadcast(room,{'type':'missile_done','id':missile_id})

def code():
    while True:
        c = ''.join(random.choices(string.digits, k=4))
        if c not in rooms: return c

async def index(_): return web.FileResponse(ROOT / 'index.html')
async def cover(_): return web.FileResponse(ROOT / 'cover.svg')

def local_ipv4():
    # UDP connect selects a local route/interface without sending a packet.
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(('192.0.2.1', 80))
        address = sock.getsockname()[0]
        if not address.startswith(('127.', '169.254.')):
            return address
    except OSError:
        pass
    finally:
        sock.close()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = info[4][0]
            if not address.startswith(('127.', '169.254.')):
                return address
    except OSError:
        pass
    return None

async def connection_info(_):
    address = local_ipv4()
    port = int(os.environ.get('PORT', '8080'))
    return web.json_response({'url': f'http://{address}:{port}' if address else None, 'ip': address, 'port': port})

async def broadcast(room, message):
    state=rooms.get(room)
    if not state:return
    payload=json.dumps(message)
    await asyncio.gather(*(s.send_str(payload) for s in list(app['sockets'].get(room,[])) if not s.closed),return_exceptions=True)

async def eliminate(room, victim_id, attacker_id, message, item_hit=False, explosion_scale=1):
    st=rooms.get(room); victim=st and st['players'].get(victim_id)
    now=asyncio.get_running_loop().time()
    if not victim or (st.get('mode')=='race' and st.get('raceFinished')) or (st.get('mode')=='hill' and st.get('hillFinished')) or not victim.get('alive',True) or victim.get('invincibleUntil',0)>now:return
    if item_hit and victim.get('shieldHits',0)>0:
        victim['shieldHits']=0;await broadcast(room,{'type':'shield_blocked','target':victim_id});await broadcast(room,{'type':'state','state':st});return
    victim['alive']=False
    attacker=st['players'].get(attacker_id)
    if attacker:attacker['score']=attacker.get('score',0)+1
    await broadcast(room,{'type':'explosion','x':victim['x'],'y':victim['y'],'color':COLORS.get(victim.get('color'),'#ff8057'),'scale':explosion_scale})
    if st.get('mode')=='hill':message=message.replace('3 seconds','1 second')
    await broadcast(room,{'type':'event','text':message})
    await broadcast(room,{'type':'state','state':st})
    async def respawn(r=room,v=victim_id):
        await asyncio.sleep(1 if st.get('mode')=='hill' else 3); current=rooms.get(r); player=current and current['players'].get(v)
        if player:
            spawn={'x':player['x'],'y':player['y'],'angle':player.get('angle',0)} if current.get('mode')=='race' else arena_spawn(current.get('map','neon'),(q for q in current['players'].values() if q['id']!=v))
            player.update(alive=True,**spawn,invincibleUntil=asyncio.get_running_loop().time()+1);await broadcast(r,{'type':'state','state':current})
    asyncio.create_task(respawn())

async def consume_shield(room,player):
    if player.get('shieldHits',0)<=0:return False
    player['shieldHits']=0
    await broadcast(room,{'type':'shield_blocked','target':player['id']})
    await broadcast(room,{'type':'state','state':rooms[room]})
    return True

async def finish_hill(room,winner_id):
    st=rooms.get(room)
    if not st or st.get('mode')!='hill' or st.get('hillFinished'):return
    winner=st['players'].get(winner_id)
    if not winner or not winner.get('alive',True):return
    st['hillFinished']=True;st['hillWinner']=winner_id
    st.setdefault('hillBestHold',{})[winner_id]=max(st.setdefault('hillBestHold',{}).get(winner_id,0),15.0)
    order=sorted(st['players'].values(),key=lambda p:st.get('hillTimeByPlayer',{}).get(p['id'],0),reverse=True)
    st['hillPlacements']=[p['id'] for p in order]
    st['hillPlacements'].remove(winner_id);st['hillPlacements'].insert(0,winner_id)
    await broadcast(room,{'type':'hill_finished','winner':winner_id,'placements':st['hillPlacements']})
    await broadcast(room,{'type':'state','state':st})

async def update_hill(room):
    st=rooms.get(room)
    if not st or st.get('mode')!='hill' or st.get('hillFinished'):return
    now=asyncio.get_running_loop().time();last=st.get('hillLastTick',now);dt=max(0,min(.25,now-last));st['hillLastTick']=now
    hill=st.get('hill',{'x':600,'y':350});inside={};progress=st.setdefault('hillProgress',{});holds=st.setdefault('hillHoldSince',{});times=st.setdefault('hillTimeByPlayer',{});best=st.setdefault('hillBestHold',{})
    for pid,p in st.get('players',{}).items():
        if p.get('alive',True) and math.dist((p['x'],p['y']),(hill['x'],hill['y']))<=60:
            inside[pid]=p
            if pid not in holds:holds[pid]=now
            times[pid]=times.get(pid,0)+dt;progress[pid]=round(now-holds[pid],2);best[pid]=max(best.get(pid,0),now-holds[pid])
        else:
            holds.pop(pid,None);progress.pop(pid,None)
    for pid in inside:
        if now-holds[pid]>=15:
            await finish_hill(room,pid);return
async def finish_race(room,winner_id):
    st=rooms.get(room)
    if not st or st.get('mode')!='race' or st.get('raceFinished'):return
    winner=st['players'].get(winner_id)
    if not winner:return
    st['raceFinished']=True;st['raceWinner']=winner_id
    st['racePlacements']=[p['id'] for p in sorted(st['players'].values(),key=lambda p:(p.get('lap',0)+track_progress(st.get('map','military'),p['x'],p['y'])),reverse=True)]
    st['racePlacements'].remove(winner_id);st['racePlacements'].insert(0,winner_id)
    await broadcast(room,{'type':'race_finished','winner':winner_id,'placements':st['racePlacements']})
    await broadcast(room,{'type':'state','state':st})

@web.middleware
async def track(req, handler):
    resp=await handler(req)
    if isinstance(resp,web.WebSocketResponse):
        pass
    return resp

app=web.Application()
app['sockets']={}
async def ws_handler(req):
    ws=web.WebSocketResponse(heartbeat=25); await ws.prepare(req)
    room=pid=None
    try:
        async for msg in ws:
            if msg.type!=WSMsgType.TEXT:continue
            try:d=json.loads(msg.data)
            except:continue
            if d.get('type')=='join':
                requested_room=d.get('code','').strip()
                if d.get('joinOnly') and requested_room not in rooms:
                    await ws.send_json({'type':'error','message':'Room not found. Check the four-digit code with the host.'})
                    await ws.close()
                    continue
                room=requested_room or code()
                if room not in rooms:
                    rooms[room]={'mode':d.get('mode','battle'),'map':d.get('map','neon'),'players':{},'items':[],'hazards':[],'hill':{'x':600,'y':350},'hillHoldSince':{},'hillProgress':{},'hillTimeByPlayer':{},'hillBestHold':{},'hillLastTick':asyncio.get_running_loop().time(),'teamMode':d.get('teamMode','duo'),'dropRate':max(5,min(60,int(d.get('dropRate',15)))),'nextDropAt':asyncio.get_running_loop().time()}
                    asyncio.create_task(run_drops(room))
                state=rooms[room]
                used={p['color'] for p in state['players'].values() if not p.get('bot')}; color=d.get('color','red')
                if color not in COLORS:color='red'
                if color in used:
                    color=next((c for c in COLORS if c not in used),color)
                pid=''.join(random.choices(string.ascii_letters+string.digits,k=8)); n=len(state['players'])
                spawn=arena_spawn(state.get('map','neon'),state['players'].values())
                if state['mode']=='race': spawn=race_spawn(state['map'],n)
                state['players'][pid]={'id':pid,'name':str(d.get('name','Tank'))[:16],'color':color,**spawn,'alive':True,'score':0,'lap':0,'progress':0,'team':n%2}
                if d.get('solo') and not any(p.get('bot') for p in state['players'].values()):
                    bid='BOT-'+pid
                    bot_spawn=arena_spawn(state.get('map','neon'),state['players'].values())
                    if state['mode']=='race': bot_spawn=race_spawn(state['map'],n+1)
                    state['players'][bid]={'id':bid,'name':'Arena AI','color':'white',**bot_spawn,'alive':True,'score':0,'lap':0,'progress':0,'team':1,'bot':True}
                    state['solo']=True
                    asyncio.create_task(run_bot(room,bid))
                app['sockets'].setdefault(room,set()).add(ws)
                await ws.send_json({'type':'welcome','id':pid,'code':room,'state':state,'colors':COLORS})
                await broadcast(room,{'type':'state','state':state})
            elif room and d.get('type')=='update':
                p=rooms.get(room,{}).get('players',{}).get(pid)
                if p:
                    locked=(rooms[room].get('mode')=='race' and rooms[room].get('raceFinished')) or (rooms[room].get('mode')=='hill' and rooms[room].get('hillFinished'))
                    if not locked:
                        for k in ('x','y','angle','alive','lap','progress'):
                            if k in d and isinstance(d[k],(int,float,bool)):
                                if rooms[room].get('mode')=='race' and k in ('x','y'):
                                    tx=d.get('x',p['x']);ty=d.get('y',p['y'])
                                    if not on_race_track(rooms[room].get('map','military'),tx,ty):continue
                                p[k]=d[k]
                    await check_track_effect(room,p)
                    if isinstance(d.get('lap'),(int,float)) and d['lap']>p.get('scoredLap',0):
                        p['score']=p.get('score',0)+(int(d['lap'])-p.get('scoredLap',0));p['scoredLap']=int(d['lap'])
                    if rooms[room].get('mode')=='race' and p.get('lap',0)>=3:await finish_race(room,pid)
                    for item in list(rooms[room].get('items',[])):
                        if (p['x']-item['x'])**2+(p['y']-item['y'])**2<28**2:
                            rooms[room]['items'].remove(item);p['heldItem']=item['kind']
                            if item.get('raceBox'):
                                rooms[room]['nextDropAt']=asyncio.get_running_loop().time()+5
                                await broadcast(room,{'type':'box_pop','x':item['x'],'y':item['y']})
                            await broadcast(room,{'type':'pickup','player':p['name'],'kind':item['kind'],'x':p['x'],'y':p['y']})
                    for hazard in list(rooms[room].get('hazards',[])):
                        if hazard['owner']!=pid and (p['x']-hazard['x'])**2+(p['y']-hazard['y'])**2<24**2:
                            rooms[room]['hazards'].remove(hazard)
                            if await consume_shield(room,p):pass
                            elif hazard['kind']=='Oil slick':await broadcast(room,{'type':'effect','target':pid,'effect':'slow','duration':3000})
                            else:await eliminate(room,pid,hazard['owner'],p['name']+' hit a mine!',item_hit=True)
                            break
                    if rooms[room].get('mode')=='hill':await update_hill(room)
                    await broadcast(room,{'type':'state','state':rooms[room]})
            elif room and d.get('type')=='config':
                old_mode=rooms[room]['mode'];old_map=rooms[room]['map'];rooms[room]['mode']=d.get('mode',rooms[room]['mode']);rooms[room]['map']=d.get('map',rooms[room]['map']);rooms[room]['teamMode']=d.get('teamMode','duo')
                if rooms[room]['mode']=='hill' and (old_mode!='hill'):
                    rooms[room].update(hillFinished=False,hillHoldSince={},hillProgress={},hillTimeByPlayer={p['id']:0 for p in rooms[room]['players'].values()},hillBestHold={},hillLastTick=asyncio.get_running_loop().time());rooms[room].pop('hillWinner',None);rooms[room].pop('hillPlacements',None)
                if rooms[room]['mode']=='race' and (old_mode!='race' or old_map!=rooms[room]['map']):
                    rooms[room]['items']=[];rooms[room]['nextDropAt']=asyncio.get_running_loop().time();rooms[room]['raceFinished']=False;rooms[room].pop('raceWinner',None);rooms[room].pop('racePlacements',None)
                    for index,player in enumerate(rooms[room]['players'].values()):player.update(**race_spawn(rooms[room]['map'],index),lap=0,progress=0,scoredLap=0)
                elif old_mode=='race' and rooms[room]['mode']!='race':rooms[room]['items']=[item for item in rooms[room]['items'] if not item.get('raceBox')]
                rooms[room]['dropRate']=max(5,min(60,int(d.get('dropRate',rooms[room].get('dropRate',15)))))
                await broadcast(room,{'type':'state','state':rooms[room]})
            elif room and d.get('type')=='hit':
                victim=rooms.get(room,{}).get('players',{}).get(d.get('target'))
                if victim and victim['id']!=pid:await eliminate(room,victim['id'],pid,victim['name']+' exploded! Respawning in 3 seconds.')
            elif room and d.get('type')=='bullet':
                shooter=rooms.get(room,{}).get('players',{}).get(pid)
                if shooter:await broadcast(room,{'type':'projectile','x':d.get('x',shooter['x']),'y':d.get('y',shooter['y']),'angle':d.get('angle',shooter.get('angle',0)),'color':COLORS.get(shooter.get('color'),'#fff'),'owner':pid,'kind':'Cannon'})
            elif room and d.get('type')=='use_special':
                st=rooms.get(room,{});p=st.get('players',{}).get(pid);now=asyncio.get_running_loop().time()
                if p and p.get('alive',True) and not ((st.get('mode')=='race' and st.get('raceFinished')) or (st.get('mode')=='hill' and st.get('hillFinished'))):
                    ready=p.get('specialReadyAt',0)
                    if now>=ready:
                        kind={'red':'fire','blue':'ice','green':'grass','purple':'teleport','orange':'earth','yellow':'speed'}.get(p.get('color'));earth_target=None
                        if kind=='earth':
                            facing=p.get('angle',0);ahead=[]
                            for rival in st['players'].values():
                                if rival['id']==pid or not rival.get('alive',True):continue
                                dx=rival['x']-p['x'];dy=rival['y']-p['y'];distance=math.hypot(dx,dy);bearing=math.atan2(dy,dx);delta=abs((bearing-facing+math.pi)%(2*math.pi)-math.pi)
                                if distance<700 and delta<1.35:ahead.append((distance,rival))
                            if ahead:earth_target=min(ahead,key=lambda pair:pair[0])[1]
                            else:await ws.send_json({'type':'special_failed','message':'Aim at a tank in front of you to use Earth.'})
                        if kind and (kind!='earth' or earth_target):
                            p['specialReadyAt']=now+10;fx={'type':'special_used','player':pid,'kind':kind,'x':p['x'],'y':p['y'],'color':p.get('color'),'cooldown':10}
                            if kind=='fire':asyncio.create_task(launch_fireball(room,pid))
                            elif kind=='speed':p['boostUntil']=now+4.5;await broadcast(room,{'type':'effect','target':pid,'effect':'boost','duration':4500})
                            elif kind=='teleport':
                                ox=p['x'];oy=p['y'];distance=220;found=False
                                while distance>=24:
                                    nx=ox+math.cos(p.get('angle',0))*distance;ny=oy+math.sin(p.get('angle',0))*distance
                                    if 35<nx<965 and 35<ny<525 and not blocked(st.get('map','neon'),nx,ny,15) and (st.get('mode')!='race' or on_race_track(st.get('map','military'),nx,ny)):
                                        p['x']=nx;p['y']=ny;fx.update(fromX=ox,fromY=oy,toX=nx,toY=ny);found=True;break
                                    distance-=16
                                if not found:fx['kind']='teleport-failed'
                            elif kind=='earth':fx['target']=earth_target['id'];asyncio.create_task(launch_earth_rock(room,pid,earth_target['id']))
                            elif kind in ('ice','grass'):
                                radius=230 if kind=='ice' else 185
                                for rival in st['players'].values():
                                    if rival['id']==pid or not rival.get('alive',True) or math.dist((p['x'],p['y']),(rival['x'],rival['y']))>radius:continue
                                    duration=2600 if kind=='ice' else 3000;rival['stunnedUntil']=now+duration/1000
                                    await broadcast(room,{'type':'effect','target':rival['id'],'effect':'ice' if kind=='ice' else 'vines','duration':duration})
                            await broadcast(room,fx);await broadcast(room,{'type':'state','state':st})
                    else:await ws.send_json({'type':'special_cooldown','remaining':round(ready-now,1)})
            elif room and d.get('type')=='use_item':
                st=rooms.get(room,{}); p=st.get('players',{}).get(pid); item=p and p.get('heldItem')
                if p and item:
                    p['heldItem']=None; now=asyncio.get_running_loop().time();await broadcast(room,{'type':'item_used','player':pid,'kind':item})
                    if item=='Boost':await broadcast(room,{'type':'effect','target':pid,'effect':'boost','duration':5000})
                    elif item=='Shield':
                        p['shieldHits']=1;await broadcast(room,{'type':'effect','target':pid,'effect':'shield','duration':600000})
                    elif item=='Repair kit':
                        p['invincibleUntil']=now+5; await broadcast(room,{'type':'effect','target':pid,'effect':'shield','duration':5000})
                    elif item=='Smoke screen':await broadcast(room,{'type':'effect','target':pid,'effect':'smoke','duration':4500})
                    elif item=='EMP pulse':
                        for rival in st['players'].values():
                            if rival['id']!=pid and not await consume_shield(room,rival):rival['stunnedUntil']=now+2.5;await broadcast(room,{'type':'effect','target':rival['id'],'effect':'stun','duration':2500})
                    elif item in ('Oil slick','Mine'):
                        theta=p.get('angle',0);hazard={'id':''.join(random.choices(string.ascii_letters+string.digits,k=7)),'kind':item,'x':p['x']-math.cos(theta)*30,'y':p['y']-math.sin(theta)*30,'owner':pid}
                        st.setdefault('hazards',[]).append(hazard);await broadcast(room,{'type':'event','text':p['name']+' deployed '+item+'!'});await broadcast(room,{'type':'state','state':st})
                    elif item in ('Homing missile','Rocket','Scatter shot'):
                        rivals=sorted((r for r in st['players'].values() if r['id']!=pid and r.get('alive',True)),key=lambda r:(r['x']-p['x'])**2+(r['y']-p['y'])**2)
                        if item=='Homing missile':
                            chosen=homing_target(st,p)
                            if chosen:asyncio.create_task(launch_homing(room,pid,chosen['id']))
                        victims=rivals[:3] if item=='Scatter shot' else [] if item=='Homing missile' else rivals[:1]
                        for victim in victims:
                            angle=math.atan2(victim['y']-p['y'],victim['x']-p['x']);await broadcast(room,{'type':'projectile','x':p['x'],'y':p['y'],'angle':angle,'color':COLORS.get(p.get('color'),'#fff'),'owner':pid,'kind':item})
                            async def missile(r=room,v=victim['id'],a=pid,delay=max(.12,math.hypot(victim['x']-p['x'],victim['y']-p['y'])/480),kind=item,name=victim['name']):
                                await asyncio.sleep(delay);await eliminate(r,v,a,'A '+kind+' hit '+name+'!',item_hit=True)
                            asyncio.create_task(missile())
                    else:await broadcast(room,{'type':'event','text':p['name']+' used '+item+'!'})
                    await broadcast(room,{'type':'state','state':st})
            elif room and d.get('type')=='event': await broadcast(room,d)
    finally:
        if room:
            app['sockets'].get(room,set()).discard(ws); st=rooms.get(room)
            if st and pid in st['players']:
                del st['players'][pid]
                if not any(not p.get('bot') for p in st['players'].values()):rooms.pop(room,None);app['sockets'].pop(room,None)
                else:await broadcast(room,{'type':'state','state':st})
    return ws

app.router.add_get('/',index);app.router.add_get('/cover.svg',cover);app.router.add_get('/api/connection',connection_info);app.router.add_get('/ws',ws_handler)

async def run_bot(room, bot_id):
    """Race through checkpoints, collect drops, and use items against rivals."""
    while room in rooms and bot_id in rooms[room]['players']:
        st=rooms[room];bot=st['players'].get(bot_id)
        targets=[p for p in st['players'].values() if p['id']!=bot_id and not p.get('bot') and p.get('alive')]
        race=st.get('mode')=='race';hill=st.get('mode')=='hill'
        if (st.get('raceFinished') and race) or (st.get('hillFinished') and hill):await asyncio.sleep(.1);continue
        if not bot or (not targets and not race and not hill) or not bot.get('alive',True):await asyncio.sleep(.25);continue
        clock=asyncio.get_running_loop().time()
        if bot.get('stunnedUntil',0)>clock:await asyncio.sleep(.1);continue
        target=min(targets,key=lambda p:(p['x']-bot['x'])**2+(p['y']-bot['y'])**2) if targets else next((p for p in st['players'].values() if not p.get('bot')),None)
        if race:await check_track_effect(room,bot)
        if race and bot.get('lap',0)>=3:
            await finish_race(room,bot_id);await asyncio.sleep(.1);continue
        held=bot.get('heldItem')
        loot=None
        if not held and st.get('items') and not hill:
            if race:
                here=track_progress(st.get('map','military'),bot['x'],bot['y'])
                loot=min(st['items'],key=lambda it:(track_progress(st.get('map','military'),it['x'],it['y'])-here)%1)
            else:loot=min(st['items'],key=lambda it:(it['x']-bot['x'])**2+(it['y']-bot['y'])**2)
        seeking=loot is not None
        if seeking:goal=(loot['x'],loot['y'])
        elif race and int(bot.get('progress',0))<len(race_points(st.get('map','military'))):goal=race_points(st.get('map','military'))[int(bot.get('progress',0))]
        elif race:goal=race_points(st.get('map','military'))[0]
        elif hill:goal=(st.get('hill',{'x':600,'y':350})['x'],st.get('hill',{'x':600,'y':350})['y'])
        else:goal=(target['x'],target['y'])
        dx=goal[0]-bot['x'];dy=goal[1]-bot['y'];dist=max(1,math.hypot(dx,dy));desired=math.atan2(dy,dx);bot['angle']=desired
        threshold=18 if seeking else 24 if race or hill else 115
        if dist>threshold:
            step=16.8*(1.55 if bot.get('boostUntil',0)>clock else 1)
            if bot.get('slowedUntil',0)>clock:step=6
            if bot.get('driftUntil',0)>clock:step*=.82
            for offset in (0,.3,-.3,.65,-.65,1.05,-1.05,1.55,-1.55,2.2,-2.2,math.pi):
                angle=desired+offset;nx=bot['x']+math.cos(angle)*step;ny=bot['y']+math.sin(angle)*step
                clear=st.get('mode')=='race' or not blocked(st.get('map','neon'),nx,ny)
                if 40<nx<960 and 40<ny<520 and clear and (not race or on_race_track(st.get('map','military'),nx,ny)):
                    bot['x']=nx;bot['y']=ny;bot['angle']=angle;break
        if loot and loot in st.get('items',[]) and math.dist((bot['x'],bot['y']),(loot['x'],loot['y']))<30:
            st['items'].remove(loot);bot['heldItem']=loot['kind'];held=loot['kind']
            if loot.get('raceBox'):
                st['nextDropAt']=asyncio.get_running_loop().time()+5
                await broadcast(room,{'type':'box_pop','x':loot['x'],'y':loot['y']})
            await broadcast(room,{'type':'pickup','player':bot['name'],'kind':held,'x':bot['x'],'y':bot['y']})
        if race and int(bot.get('progress',0))<len(race_points(st.get('map','military'))) and math.dist((bot['x'],bot['y']),race_points(st.get('map','military'))[int(bot['progress'])])<35:
            bot['progress']=int(bot.get('progress',0))+1
        elif race and int(bot.get('progress',0))>=len(race_points(st.get('map','military'))) and math.dist((bot['x'],bot['y']),race_points(st.get('map','military'))[0])<30:
            bot['lap']=bot.get('lap',0)+1;bot['score']=bot.get('score',0)+1;bot['progress']=0
            if bot['lap']>=3:await finish_race(room,bot_id)
        item=bot.get('heldItem');now=asyncio.get_running_loop().time()
        if target and target.get('alive',True) and math.dist((bot['x'],bot['y']),(target['x'],target['y']))<900 and now>=bot.get('megaReadyAt',0):
            bot['megaReadyAt']=now+10;asyncio.create_task(launch_mega_missile(room,bot_id,target['id']))
        if item in ('Homing missile','Rocket','Scatter shot'):
            aim_target=homing_target(st,bot) if item=='Homing missile' else target
            target_dist=math.dist((bot['x'],bot['y']),(aim_target['x'],aim_target['y'])) if aim_target else 9999
            if target_dist<500 and now>bot.get('itemAfter',0) and (race or clear_shot(st.get('map','neon'),bot['x'],bot['y'],target['x'],target['y'])):
                bot['itemAfter']=now+1.2;bot['heldItem']=None;await broadcast(room,{'type':'item_used','player':bot_id,'kind':item})
                if item=='Homing missile' and aim_target:asyncio.create_task(launch_homing(room,bot_id,aim_target['id']))
                victims=sorted((q for q in targets if q.get('alive',True)),key=lambda q:(q['x']-bot['x'])**2+(q['y']-bot['y'])**2) if item!='Homing missile' else []
                victims=victims[:3] if item=='Scatter shot' else victims[:1]
                for victim in victims:
                    angle=math.atan2(victim['y']-bot['y'],victim['x']-bot['x'])
                    await broadcast(room,{'type':'projectile','x':bot['x']+math.cos(angle)*20,'y':bot['y']+math.sin(angle)*20,'angle':angle,'color':COLORS.get(bot.get('color'),'#fff'),'owner':bot_id,'kind':item})
                    async def item_shot(r=room,v=victim['id'],attacker=bot_id,delay=max(.12,math.dist((bot['x'],bot['y']),(victim['x'],victim['y']))/480),kind=item,name=victim['name']):
                        await asyncio.sleep(delay);await eliminate(r,v,attacker,'Arena AI used '+kind+' on '+name+'!',item_hit=True)
                    asyncio.create_task(item_shot())
        elif item:
            bot['heldItem']=None;await broadcast(room,{'type':'item_used','player':bot_id,'kind':item})
            if item=='Boost':bot['boostUntil']=now+5;await broadcast(room,{'type':'effect','target':bot_id,'effect':'boost','duration':5000})
            elif item=='Shield':bot['shieldHits']=1;await broadcast(room,{'type':'effect','target':bot_id,'effect':'shield','duration':600000})
            elif item=='Repair kit':bot['invincibleUntil']=now+5;await broadcast(room,{'type':'effect','target':bot_id,'effect':'shield','duration':5000})
            elif item=='Smoke screen':await broadcast(room,{'type':'effect','target':bot_id,'effect':'smoke','duration':4500})
            elif item=='EMP pulse':
                for rival in targets:
                    if not await consume_shield(room,rival):rival['stunnedUntil']=now+2.5;await broadcast(room,{'type':'effect','target':rival['id'],'effect':'stun','duration':2500})
            elif item in ('Oil slick','Mine'):
                angle=bot.get('angle',0);st.setdefault('hazards',[]).append({'id':''.join(random.choices(string.ascii_letters+string.digits,k=7)),'kind':item,'x':bot['x']-math.cos(angle)*30,'y':bot['y']-math.sin(angle)*30,'owner':bot_id})
                await broadcast(room,{'type':'state','state':st})
        if race and int(bot.get('progress',0))>=len(race_points(st.get('map','military'))):goal=race_points(st.get('map','military'))[0]
        for hazard in list(st.get('hazards',[])):
            if hazard['owner']!=bot_id and math.dist((bot['x'],bot['y']),(hazard['x'],hazard['y']))<24:
                st['hazards'].remove(hazard)
                if await consume_shield(room,bot):pass
                elif hazard['kind']=='Oil slick':bot['slowedUntil']=now+3;await broadcast(room,{'type':'effect','target':bot_id,'effect':'slow','duration':3000})
                else:await eliminate(room,bot_id,hazard['owner'],'Arena AI hit a mine!',item_hit=True)
                break
        if not race and not bot.get('heldItem') and target and target.get('alive',True) and math.dist((bot['x'],bot['y']),(target['x'],target['y']))<(620 if hill else 300) and now>bot.get('shootAfter',0) and (hill or random.random()<.16) and clear_shot(st.get('map','neon'),bot['x'],bot['y'],target['x'],target['y']):
            bot['shootAfter']=now+1.4;angle=math.atan2(target['y']-bot['y'],target['x']-bot['x'])
            await broadcast(room,{'type':'projectile','x':bot['x']+math.cos(angle)*20,'y':bot['y']+math.sin(angle)*20,'angle':angle,'color':COLORS.get(bot.get('color'),'#fff'),'owner':bot_id,'kind':'Cannon'})
            async def bot_shot(r=room,v=target['id'],attacker=bot_id,delay=max(.12,math.dist((bot['x'],bot['y']),(target['x'],target['y']))/480),name=target['name']):
                await asyncio.sleep(delay);await eliminate(r,v,attacker,'Arena AI hit '+name+'! Respawning in 3 seconds.')
            asyncio.create_task(bot_shot())
        if hill:await update_hill(room)
        await broadcast(room,{'type':'state','state':st});await asyncio.sleep(.1)

async def run_drops(room):
    """Maintain one five-second-regenerating missile box on the race circuit."""
    while room in rooms:
        st=rooms[room];mode=st.get('mode')
        if st.get('players') and mode=='race':
            if st.get('raceFinished'):
                await asyncio.sleep(.2);continue
            now=asyncio.get_running_loop().time()
            if not st.get('items') and now>=st.get('nextDropAt',now):
                map_name=st.get('map','military');trailer=min(st['players'].values(),key=lambda p:race_rank(p,map_name))
                x,y=track_position(map_name,track_progress(map_name,trailer['x'],trailer['y'])+.14)
                st['items']=[{'id':''.join(random.choices(string.ascii_letters+string.digits,k=7)),'kind':race_item_for(st),'x':x,'y':y,'raceBox':True}]
                await broadcast(room,{'type':'state','state':st})
            await asyncio.sleep(.2);continue
        if st.get('players') and mode in ('battle','hill','teams'):
            st['items'].append({'id':''.join(random.choices(string.ascii_letters+string.digits,k=7)),'kind':random.choice(DROP_ITEMS),'x':random.randint(75,925),'y':random.randint(75,485)})
            await broadcast(room,{'type':'state','state':st})
        await asyncio.sleep(max(5,min(60,int(st.get('dropRate',15)))))

if __name__=='__main__': web.run_app(app,host='0.0.0.0',port=int(os.environ.get('PORT','8080')))
