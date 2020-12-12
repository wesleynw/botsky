import os
import json
import asyncio
import logging 
import traceback
import discord
from re import sub
from emoji import demojize
from random import choice, random
from datetime import datetime, timedelta
from discord.utils import get
from discord.ext import commands, tasks
from pymongo import MongoClient

token = os.environ.get('DISCORDTOKEN')
intents = discord.Intents().all()
bot = commands.Bot(command_prefix='$', intents=intents)
embed_color = 0x5482f7

db_client = MongoClient('localhost',27017)
db = db_client["discord-db"]

with open('questions.json') as f:
    questions = json.load(f)

## EVENTS
@bot.event
async def on_ready():
    logging.info(f'{bot.user.name} has connected to Discord!')
    change_presense.start()
    count_hourly.start()
    daily_leaderboard.start()
    birthday_annoucements.start()

@bot.event 
async def on_error(event, *args, **kwargs):
    logging.warning(traceback.format_exc())

@bot.event
async def on_raw_reaction_add(payload):
    rules_channel = bot.get_channel(780288110281621505)
    guild = bot.get_guild(payload.guild_id)
    member = payload.member
    emoji = payload.emoji

    if bot.get_channel(payload.channel_id) == rules_channel and member != bot.user:
        if emoji.name == "✅":
            # role = guild.get_role(780289692918087690) #new
            # await member.remove_roles(role)
            return
        elif emoji.name == "💯":
            role = guild.get_role(771540512825409559) #among us
            await member.add_roles(role)
        elif emoji.name == '🔞':
            role = guild.get_role(777460068035592252) #crack addict
            await member.add_roles(role)
        else:
            color_roles = list(get(guild.roles, name=x) for x in ['red', 'orange', 'yellow', 'green', 'blue', 'purple'])
            wanted_role = [i for i in color_roles if i.name in demojize(payload.emoji.name)][0]
            current_roles = [x.name for x in member.roles]
            await member.remove_roles(*[x for x in color_roles if x.name != wanted_role.name and x.name in current_roles])
            await member.add_roles(wanted_role)
            
@bot.event
async def on_raw_reaction_remove(payload):
    rules_channel = bot.get_channel(780288110281621505)
    guild = bot.get_guild(payload.guild_id)
    member = await guild.fetch_member(payload.user_id)
    emoji = payload.emoji

    if bot.get_channel(payload.channel_id) == rules_channel:
        if emoji.name == "✅":
            role = guild.get_role(780289692918087690) #new
            await member.add_roles(role)
        elif emoji.name == "💯":
            role = guild.get_role(771540512825409559) #among us
            await member.remove_roles(role)
        elif emoji.name == '🔞':
            role = guild.get_role(777460068035592252) #crack addict
            await member.remove_roles(role)
        else:
            color_roles = list(get(guild.roles, name=x) for x in ['red', 'orange', 'yellow', 'green', 'blue', 'purple'])
            selected_role = [i for i in color_roles if i.name in demojize(payload.emoji.name)][0]
            current_roles = [x.name for x in member.roles]
            await member.remove_roles(*[x for x in color_roles if x.name == selected_role.name and x.name in current_roles])




### TASKS
@tasks.loop(minutes=15)
async def change_presense():
    activities = [
        discord.Game('with myself ;)'), discord.Activity(name='MS Paint', type=discord.ActivityType.competing), discord.Game('violin'), 
        discord.Activity(name='you', type=discord.ActivityType.listening), discord.Activity(name='100 gecs on Spotify', type=discord.ActivityType.listening),
        discord.Game('GTA in real life'), discord.Activity(name='A24 films', type=discord.ActivityType.watching), discord.Activity(name='@Wesley (my maker)', type=discord.ActivityType.listening),
        discord.Game('Sims (Discord Bot DLC)')]
    await bot.change_presence(activity=choice(activities))

@tasks.loop(hours=24)
async def birthday_annoucements():
    # trigger every day at 9AM PST (17:00 UTC)
    await sleep_until_hour(17)
    for guild in bot.guilds:
        collection = db[str(guild.id)]
        try:
            announcements_channel = bot.get_channel(collection.find_one({'announcements_channel' : {'$exists' : True}}).get('announcements_channel'))
            if announcements_channel == None:
                return
        except AttributeError:
            return

        birthdays = collection.find_one({'birthdays' : {'$exists' : True}}).get('birthdays')
        for k,v in birthdays.items():
            if datetime.strptime(v, "%m/%d").replace(year=datetime.now().year).date() == datetime.today().date():
                # TODO: change all instances of fetch_member to get_member (fetch member is an API call and is slower)
                member = guild.get_member(int(k))
                await announcements_channel.send(f"{guild.default_role} with a happy birthday to {member.mention}")



@tasks.loop(hours=1)
async def count_hourly():
    if datetime.utcnow().minute != 0:
        await asyncio.sleep((60-datetime.utcnow().minute)*60)


    for guild in bot.guilds:
        collection = db[str(guild.id)]
        try:
            counting_channel = bot.get_channel(collection.find_one({'counting_channel' : {'$exists' : True}}).get('counting_channel'))
            if counting_channel == None:
                return
        except AttributeError:
            return 

        payload = await counting_channel.history(limit=1).flatten()
        try: 
            payload = int(sub("[^0-9]", "", payload[0].content)) + 1
            await counting_channel.send(payload)
        except ValueError:
            pass

@tasks.loop(hours=24)
async def daily_leaderboard():  
    # trigger everyday at 6UTC (22:00 PST)
    await sleep_until_hour(6)

    logging.info('Starting daily leaderboard...')

    for guild in bot.guilds:
        collection = db[str(guild.id)]
        try: 
            counting_channel = bot.get_channel(collection.find_one({'counting_channel' : {'$exists' : True}}).get('counting_channel'))
            announcements_channel = bot.get_channel(collection.find_one({'announcements_channel' : {'$exists' : True}}).get('announcements_channel'))
            if counting_channel == None or announcements_channel == None:
                return
        except:
            logging.info("Exception in daily_leaderboard")
            return

        # retrieve and send last week's stats
        # need to calculate previous ranks and efficiency now, defaults to oldest_first=True 
        ranks_and_efficiency = await calc_ranks_and_efficiency(guild.members, counting_channel, after=datetime.utcnow()-timedelta(days=1))
        prev_ranks_and_efficiency = await calc_ranks_and_efficiency(guild.members, counting_channel, after=datetime.utcnow()-timedelta(days=2), before=datetime.utcnow()-timedelta(days=1))
        embed = discord.Embed(color=embed_color)
        embed.add_field(name=f'Daily Leaderboard 💯', value='___', inline=False)


        def search(lst, item):
            for i in range(len(lst)):
                part = lst[i]
                for j in range(len(part)):
                    if part[j] == item: return (i, j)
            return None

        for i in range(min(10, len(ranks_and_efficiency))):
            # ranks_and_efficiency is in format [ [rank, member, efficiency], [], []] listed in order of rank
            place = i
            if place == 0:
                place = ":first_place:"
            elif i == 1:
                place = ":second_place:"
            elif i == 2:
                place = ":third_place:"
            prev_member = search(prev_ranks_and_efficiency, ranks_and_efficiency[i][1])
            change_in_rank = prev_ranks_and_efficiency[prev_member[0]][0] - ranks_and_efficiency[i][0]
            direction = ':record_button:'
            if change_in_rank > 0:
                direction = ':arrow_up:'
            elif change_in_rank < 0:
                direction = ':arrow_down:'
            else: 
                change_in_rank = ''
            embed.add_field(name=f'**{place}**. {ranks_and_efficiency[i][1].display_name}', value=f'{direction} {change_in_rank} --- efficiency: **{ranks_and_efficiency[i][2]}%**', inline=False)

        await announcements_channel.send(embed=embed)




### EVENTS
@bot.event
async def on_message(message):
    # process all other commands first
    await bot.process_commands(message)
    if message.author == bot.user:
        return

    try:
        collection = db[str(message.guild.id)]
        counting_channel = bot.get_channel(collection.find_one({'counting_channel' : {'$exists' : True}}).get('counting_channel'))
    except Exception as e:
        print(e)
        counting_channel = None
    
    try:
        collection = db[str(message.guild.id)]
        story_channel = bot.get_channel(collection.find_one({'story_channel' : {'$exists' : True}}).get('story_channel'))
    except Exception as e:
        print(e)
        story_channel = None

    # check if someone counted incorrectly in the counting channel
    if message.channel == counting_channel:
        # try to get counting channel
        
        # for now, all messages need to contain the string 'fix your number'
        # TODO: find a better way to do this, if error message doesn't contain 'fix your number'
        on_error_messages = ["Hey {0}! You absolute dumbass! Do you not know how to count? Fix your number.",
            "{0} are you dense? Please fix your number.",
            "{0}. Bit sad innit?. The fact that you can't count, I mean. Fix your number.",
            "{0} you sick fuck, fix your number.",
            "Hey {0} does _this_ smell like chloroform? Please fix your number 🤡",
            "{0} i'll permaban you if you don't fix your number.",
            "You're on thin fucking ice {0}. Don't misstep. Fix your number."]

        latest_mesgs = [x for x in await counting_channel.history(limit=4).flatten() if 'fix your number' not in x.content.lower()]
        try: 
            latest_count = int(sub("[^0-9]", "", latest_mesgs[0].content))
            latest_count_2 = int(sub("[^0-9]", "", latest_mesgs[1].content))
        except: 
            print('handling exception in on_message')
            latest_count, latest_count_2 = 0, 0

        if latest_count != latest_count_2+1:
            mesg = choice(on_error_messages).format(message.author.mention)
            await counting_channel.send(mesg, delete_after=10)
            if 'dumbass' not in [x.name for x in message.author.roles]:
                await message.author.add_roles(get(message.guild.roles, name='dumbass')) # dumbass role
    elif message.channel != story_channel:
        if random() < 0.02:
            await message.channel.send(message.author.mention+" "+choice(questions))





### COMMANDS
@bot.command()
async def ping(ctx):
    suffix = ['bitches', 'you sick fuck', 'sir', 'daddy 🥺', 'master', 'papa', 'whores', "y'all"]
    await ctx.send(f'Pong! **{round(bot.latency, 3)}ms** {choice(suffix)}')

@bot.command()
async def link(ctx, *args):
    collection = db[str(ctx.guild.id)]
    #set counting channel
    if args[0] == 'counting':
        try:
            counting_channel = int(sub("[^0-9]", "", args[1]))
        except:
            counting_channel = None
        if bot.get_channel(counting_channel) is None:
            await ctx.send("This channel doesn't exist!")
            return 
        
        # replace_one(filter, replacement, upsert=True)
        collection.replace_one({"counting_channel" : {'$exists' : True}}, {"counting_channel" : counting_channel}, True)
        await ctx.send(f'The counting channel has been set to {args[1]}')
    # set story channel
    elif args[0] == 'story':
        try:
            story_channel = int(sub("[^0-9]", "", args[1]))
        except:
            story_channel = None
        if bot.get_channel(story_channel) is None:
            await ctx.send("This channel doesn't exist!")
            return 
        collection.replace_one({"story_channel" : {"$exists" : True}}, {"story_channel" : story_channel}, True)
        await ctx.send(f'The story channel has been set to {args[1]}')
    # set announcements channel
    elif args[0] == 'announcements':
        try:
            announcements_channel = int(sub("[^0-9]", "", args[1]))
        except:
            announcements_channel = None
        if bot.get_channel(announcements_channel) is None:
            await ctx.send("This channel doesn't exist!")
            return 
        collection.replace_one({"announcements_channel" : {"$exists" : True}}, {"announcements_channel" : announcements_channel}, True)
        await ctx.send(f'The announcements channel has been set to {args[1]}')
    else:
        await ctx.send("Something you entered didn't make sense...")
        return

@bot.command()  
async def leaderboard(ctx, *args):
    async with ctx.channel.typing():
        try: 
            collection = db[str(ctx.guild.id)]
            counting_channel = bot.get_channel(collection.find_one({'counting_channel' : {'$exists' : True}}).get('counting_channel'))
        except Exception as e:
            print(e)
            await ctx.send('You must set a counting channel using **$link counting** ***#channel***.')
            return
        
        interval = 'All Time'
        if len(args) != 0:
            if args[0] == 'daily':
                td = datetime.utcnow() - timedelta(days=1)
                interval = 'Daily'
            elif args[0] == 'weekly':
                td = datetime.utcnow() - timedelta(weeks=1)
                interval = 'Weekly'
            elif args[0] == 'monthly':
                td = datetime.utcnow() - timedelta(weeks=4)
                interval = 'Monthly'
            else:
                await ctx.send('⚠️Error!⚠️ Arguments must be either **empty**(for all time), **daily**, **weekly**, or **monthly**.')
                return
        else:
            oldest_mesg = await counting_channel.history(limit=1, oldest_first=True).flatten()
            td = oldest_mesg[0].created_at
    
        # message_hist = await counting_channel.history(limit=None, after=td).flatten()
        embed = discord.Embed(color=embed_color)
        embed.add_field(name=f'{interval} Leaderboard 💯', value='___', inline=False)
    
        # ranks_and_efficiency = await calc_ranks_and_efficiency(ctx.guild.members, message_hist, (datetime.utcnow() - td).total_seconds()/3600)
        ranks_and_efficiency = await calc_ranks_and_efficiency(ctx.guild.members, counting_channel, td)

        for i in range(min(5, len(ranks_and_efficiency))):
            embed.add_field(name=f"***{i+1}***. {ranks_and_efficiency[i][1].display_name}", value=f"efficiency: **{ranks_and_efficiency[i][2]}%**", inline=False)

        await ctx.send(embed=embed)

@bot.command()
async def stats(ctx, *args):
    async with ctx.channel.typing():
        try: 
            collection = db[str(ctx.guild.id)]
            counting_channel = bot.get_channel(collection.find_one({'counting_channel' : {'$exists' : True}}).get('counting_channel'))
        except Exception:
            await ctx.send('You must set a counting channel using **$link counting** ***#channel***.')
            return

        member = ctx.author
        if len(args) != 0:
            try: 
                member = bot.get_user(int(sub("[^0-9]", "", args[0])))
            except:
                await ctx.send("Something went wrong. Try running this command again.")
                pass

        
        now = datetime.utcnow()
        slowmode = counting_channel.slowmode_delay
        counting_channel_history = await counting_channel.history(limit=None).flatten()

        # returns in format: [member, rank, efficiency]
        daily_stats = await calculate_member_stats(ctx.guild.members, member, counting_channel_history, slowmode, now - timedelta(days=1))
        prev_daily_stats = await calculate_member_stats(ctx.guild.members, member, counting_channel_history, slowmode, now - timedelta(days=2), now - timedelta(days=1))
        weekly_stats = await calculate_member_stats(ctx.guild.members, member, counting_channel_history, slowmode, now - timedelta(weeks=1))
        prev_weekly_stats = await calculate_member_stats(ctx.guild.members, member, counting_channel_history, slowmode, now - timedelta(weeks=2), now - timedelta(weeks=1))

        monthly_stats = await calculate_member_stats(ctx.guild.members, member, counting_channel_history, slowmode, now - timedelta(weeks=4))
        prev_monthly_stats = await calculate_member_stats(ctx.guild.members, member, counting_channel_history, slowmode, now - timedelta(weeks=8), now - timedelta(weeks=4))


        embed = discord.Embed(color=member.color)
        embed.set_author(name=member.name+"'s stats", icon_url=member.avatar_url)

        daily_direction = 'Up' if daily_stats[2] > prev_daily_stats[2] else 'Down'
        daily_bar = f'[■](https://youtu.be/dQw4w9WgXcQ)'*min(10, round(daily_stats[2]/10)) + "[□](https://youtu.be/dQw4w9WgXcQ)"*(10-round(daily_stats[2]/10)) + f" ({daily_stats[2]}%)"+f"\n```{daily_direction} {round(daily_stats[2]-prev_daily_stats[2], 2)}% from yesterday```"
        embed.add_field(name="Daily - Ranked #"+str(daily_stats[1]), value=daily_bar)

        weekly_direction = 'Up' if weekly_stats[2] > prev_weekly_stats[2] else 'Down'
        weekly_bar = f'[■](https://youtu.be/dQw4w9WgXcQ)'*min(10, round(weekly_stats[2]/10)) + "[□](https://youtu.be/dQw4w9WgXcQ)"*(10-round(weekly_stats[2]/10)) + f" ({weekly_stats[2]}%)"+f"\n```{weekly_direction} {round(weekly_stats[2]-prev_weekly_stats[2], 2)}% from last week```"
        embed.add_field(name='Weekly - Ranked #'+str(weekly_stats[1]), value=weekly_bar)

        monthly_direction = 'Up' if monthly_stats[2] > prev_monthly_stats[2] else 'Down'
        monthly_bar = f'[■](https://youtu.be/dQw4w9WgXcQ)'*min(10, round(monthly_stats[2]/10)) + "[□](https://youtu.be/dQw4w9WgXcQ)"*(10-round(monthly_stats[2]/10)) + f" ({monthly_stats[2]}%)"+f"\n```{monthly_direction} {round(monthly_stats[2]-prev_monthly_stats[2], 2)}% from last month```"
        embed.add_field(name='Monthly - Ranked #'+str(monthly_stats[1]), value=monthly_bar)

        await ctx.send(embed=embed)
        
     
@bot.command()
async def story(ctx, arg : int = 1):
    async with ctx.channel.typing():
        collection = db[str(ctx.guild.id)]
        try:
            story_channel = bot.get_channel(collection.find_one({'story_channel' : {'$exists' : True}}).get('story_channel'))
        except Exception as e:
            print(e) 
            await ctx.send('You must set a counting channel using **$link counting** ***#channel***.')
            return

        text = ''
        async for message in story_channel.history(limit=None, oldest_first=True):
            if not message.attachments:
                text += message.content + ' '
            else: 
                text += '$asdf$'
        # TODO: fix for if the number it out of range
        if len(text) > 2000:
            await ctx.send("The " + text.split('$asdf$')[arg][:2000])
            await ctx.send(text.split('$asdf$'[arg][2000:]))
        else:
            await ctx.send("The " + text.split('$asdf$')[arg])     

@bot.command()
async def dm_owner(ctx, *args):
    member = bot.get_user(184880932476420097)
    await member.send(' '.join(args))

@bot.command()
async def length(ctx, *args):
    dick_names = ['penis', 'cock', 'dong', 'member', 'phallus', 'dick', 'pecker', 'trouser snake', 'willy']
    try: 
        user = bot.get_user(int(sub("[^0-9]", "", args[0])))
    except:
        user = ctx.author

    length = round(user.id / 10**17, 1)
    if user.id == 184880932476420097:
           await ctx.send(f"{ctx.author.mention}'s {choice(dick_names)} length is 11 inches.") 
           return
    await ctx.send(f"{user.mention}'s {choice(dick_names)} length is {length} inches.")

@bot.command()
async def birthday(ctx, arg):
    try:
        b = arg.split('/')
        mm = int(sub("[^0-9]", "", b[0]))
        dd = int(sub("[^0-9]", "", b[1]))
        if mm not in range(1,13) or dd not in range(1,32):
            raise ValueError 
    except ValueError:
        await ctx.send('The birthday you entered was invalid, please enter it in the format MM/DD.')
        return 
    collection = db[str(ctx.guild.id)]
    # ctx.author.id can provide a Member or User object depending on if in server or DM
    collection.replace_one({"birthdays" : {'$exists' : True}}, {"birthdays" : {str(ctx.author.id) : arg}}, upsert=True)
    await ctx.send('Got it.')

# @bot.command()
# async def penis(ctx, *args):
#     collection = db[str(ctx.guild.id)]
#     # create a penis if the member doesn't already have one
#     if collection.find_one({"penis_data" : {str(ctx.author.id) : {'$exists' : True}}}) is None:
#         collection.insert_one({"penis_data" : {str(ctx.author.id) : 
#         {
#             "length" : round(ctx.author.id / 10**17, 1),
#             "sperm_count" : 150,
#             "condom_ct" : 0,
#             "horniness" : 10,
#             "stamina" : 35,
#             "stress" : 50,
#             "vasectomy" : False
#         }
#         }})

#     # display current penis stats
#     if len(args) == 0:
        
        


### FUNCTIONS
async def calc_ranks_and_efficiency(members, counting_channel, after, before=None):
    if before is None:
        before = datetime.utcnow()
    message_hist = await counting_channel.history(limit=None, after=after, before=before).flatten()
    # .slowmode_delay is in seconds
    possible_counts_interval = (before - after).total_seconds() / counting_channel.slowmode_delay
    efficiency_stats = []
    for member in members:
        counter = 0
        for message in message_hist:
            if message.author == member:
                counter += 1
        efficiency_stats.append([member, round(counter / possible_counts_interval * 100, 2)])
    
    # sort efficiencies low to high
    efficiency_stats = sorted(efficiency_stats, key=lambda x: x[1], reverse=True)
    ranks_and_efficiency = []
    for i in range(len(efficiency_stats)):
        # returns in format [ [rank, member, efficiency], [], [] ]
        ranks_and_efficiency.append([i+1, efficiency_stats[i][0], efficiency_stats[i][1]])
    return ranks_and_efficiency

# rewrite function to take counting history as an argument to lessen impact on api
async def calculate_member_stats(members, req_member, channel_history, slowmode_delay, after, before=None):
    if before is None:
        before = datetime.utcnow()

    channel_history = [x for x in channel_history if x.created_at > after and x.created_at < before]
    # .slowmode_delay is in seconds
    possible_counts_interval = (before - after).total_seconds() / slowmode_delay

    stats = []
    for member in members:
        counter = 0
        for message in channel_history:
            if message.author == member:
                counter +=1
        stats.append([member, round(counter / possible_counts_interval * 100, 2)])

    # sort efficiencies low to high
    efficiency_stats = sorted(stats, key=lambda x: x[1], reverse=True)
    for i,e in enumerate(efficiency_stats):
        if e[0] == req_member:
            # format: [member, rank, efficiency]
            return [e[0], i+1, e[1]]


async def sleep_until_hour(hour_utc : int):
    # sleep until the specified datetime
    now = datetime.utcnow()
    if now.hour != hour_utc or now.minute != 0:
        if now.hour < hour_utc:
            wait_until = now.replace(hour=hour_utc, minute=0, second=0, microsecond=0)
            await asyncio.sleep((wait_until - now).total_seconds())
        else:
            wait_until = now.replace(day=now.day+1, hour=hour_utc, minute=0, second=0, microsecond=0)
            await asyncio.sleep((wait_until - now).total_seconds())




### RUN
bot.run(token)
