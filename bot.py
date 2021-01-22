import discord
import logging 
import os
import json
import asyncio
import inflect
import textwrap
import traceback
from re import sub
from emoji import demojize
from random import choice, random
from datetime import datetime, timedelta
from discord.utils import get
from discord.ext import commands, tasks
from pymongo import MongoClient

logging.basicConfig(level=logging.INFO)

token = os.environ.get('DISCORDTOKEN')
intents = discord.Intents().default()
intents.members = True

bot = commands.Bot(command_prefix='$', intents=intents)

db_client = MongoClient('localhost',27017)
db = db_client["discord-db"]

with open('questions.json') as f:
    questions = json.load(f)
with open('activities.json') as f:
    activities = json.load(f)

## EVENTS
@bot.event
async def on_ready():
    logging.info(f'{bot.user.name} has connected to Discord!')
    change_presense.start()
    count_hourly.start()
    daily_leaderboard.start()
    floppa_friday.start()

async def is_admin(ctx):
    return ctx.author.guild_permissions.administrator or ctx.author.id == 184880932476420097

@bot.event
async def on_raw_reaction_add(payload):
    rules_channel = bot.get_channel(780288110281621505)
    guild = bot.get_guild(payload.guild_id)
    member = payload.member
    emoji = payload.emoji

    if bot.get_channel(payload.channel_id) == rules_channel and member != bot.user:
        if emoji.name == "💯":
            role = guild.get_role(771540512825409559) #among us
            await member.add_roles(role)
        elif emoji.name == '🔞':
            role = guild.get_role(777460068035592252) #crack addict
            await member.add_roles(role)
        else:
            #TODO: figure out how to get rid of get() command
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
    activity = discord.Game(choice(activities))
    await bot.change_presence(activity=activity)

# TODO: make this so it changes per slowmode delay
@tasks.loop(hours=1)
async def count_hourly():
    if datetime.utcnow().minute != 0:
        await asyncio.sleep((60-datetime.utcnow().minute)*60)

    for guild in bot.guilds:
        collection = db[str(guild.id)]
        counting_channel = bot.get_channel((collection.find_one({'counting_channel' : {'$exists' : True}}) or {0:0}).get('counting_channel'))
        disabled_flag = (collection.find_one({'disable_counting' : {'$exists' : True}}) or {0:0}).get('disable_counting', False)
        if counting_channel is None or disabled_flag:
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
    for guild in bot.guilds:
        collection = db[str(guild.id)]
        announcements_channel = bot.get_channel(collection.find_one({'announcements_channel' : {'$exists' : True}}).get('announcements_channel'))
        if announcements_channel == None:
            return

        await leaderboard_print(announcements_channel, guild)

@tasks.loop(hours=168)
async def floppa_friday():
    # trigger every friday at 20 UTC (12:00 PST)
    # there has to be a more efficient way to do this
    while datetime.now().weekday() != 4:
        await asyncio.sleep(24 * 60 * 60)

    await sleep_until_hour(20)
    for guild in bot.guilds:
        collection = db[str(guild.id)]
        try: 
            announcements_channel = bot.get_channel(collection.find_one({'announcements_channel' : {'$exists' : True}}).get('announcements_channel'))
        except:
            return

        await announcements_channel.send(file=discord.File('floppa_friday.mov'))

    


### EVENTS
@bot.event
async def on_message(message):
    # process all other commands first
    await bot.process_commands(message)
    if message.author == bot.user:
        return

    collection = db[str(message.guild.id)]
    counting_channel = bot.get_channel((collection.find_one({'counting_channel' : {'$exists' : True}}) or {0:0}).get('counting_channel'))
    story_channel = bot.get_channel((collection.find_one({'story_channel' : {'$exists' : True}}) or {0:0}).get('story_channel'))

    # check if someone counted incorrectly in the counting channel
    if message.channel == counting_channel:
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
            logging.warning("handling exception in on_message")
            latest_count, latest_count_2 = 0, 0

        if latest_count != latest_count_2+1:
            mesg = choice(on_error_messages).format(message.author.mention)
            await counting_channel.send(mesg, delete_after=10)
    elif message.channel != story_channel:
        if 'c' in message.content.lower():
            collection = db[str(message.guild.id)]
            current_strikes = (collection.find_one({'strikes' : {'$exists' : True}}) or {0:0}).get('strikes', {0:0}).get(str(message.author.id), 0) + 1

            if current_strikes < 3:
                collection.replace_one({"strikes" : {'$exists' : True}}, {"strikes" : {str(message.author.id) : current_strikes}}, upsert=True)
                p = inflect.engine()
                await message.channel.send(f'{message.author.mention} You have used a forbidden letter. That was your {p.ordinal(current_strikes)} strike.')
            elif current_strikes >=3:
                return
            else: 
                await message.channel.send(f"{message.author.mention} That was your 3rd strike. You are out. I'm putting you on timeout for the next 15 minutes.")
                out = get(message.guild.roles, name = 'OUT')
                await message.author.add_roles(out)

                collection.replace_one({"strikes" : {'$exists' : True}}, {"strikes" : {str(message.author.id) : 3}}, upsert=True)
                await asyncio.sleep(15 * 60)
                await message.author.remove_roles(out)
                collection.replace_one({"strikes" : {'$exists' : True}}, {"strikes" : {str(message.author.id) : 0}}, upsert=True)
        if 'tuesday' in message.content.lower():
            await message.channel.send(file=discord.File('tueday.png'))
        if 'when' in message.content.lower():
            await message.channel.send('like when did I ask')
        # 2% chance of sending a random message
        if random() < 0.001:
            await message.channel.send(message.author.mention+" "+choice(questions))

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        await ctx.send("You don't have permission to run this command...")




### COMMANDS
@bot.command()
async def ping(ctx):
    await ctx.send(f'Pong! **{round(bot.latency, 3)}ms**.')

@bot.command()
async def strikes(ctx, member : discord.Member = None):
    member = member or ctx.author
    collection = db[str(ctx.guild.id)]
    current_strikes = (collection.find_one({'strikes' : {'$exists' : True}}) or {0:0}).get('strikes', {0:0}).get(str(ctx.author.id), 0)
    if current_strikes is 3:
        await ctx.channel.send(f"{member.mention} has {current_strikes} strikes and is currently on timeout.")
    else:
        await ctx.channel.send(f"{member.mention} has {current_strikes} strikes.")

@bot.command()
@commands.check(is_admin)
async def link(ctx, category : str, channel : discord.TextChannel):
    channel_types = ['counting', 'announcements', 'onewordstory']
    if category not in channel_types:
        raise commands.BadArgument

    # replace_one(filter, replacement, upsert=True)
    channel_str = category + "_channel"
    collection = db[str(ctx.guild.id)]
    collection.replace_one({channel_str : {'$exists' : True}}, {channel_str : channel.id}, True)
    await ctx.send(f"The {category} channel has been set to {channel.mention}")
@link.error
async def link_error(ctx, error):
    if isinstance(error, commands.BadArgument):
        await ctx.send("That channel or channel type doesn't exist...")

@bot.command()  
async def leaderboard(ctx, *args):
    await leaderboard_print(ctx.channel, ctx.guild, *args)
async def leaderboard_print(channel, guild, *args):
    async with channel.typing():
        try: 
            collection = db[str(guild.id)]
            counting_channel = bot.get_channel(collection.find_one({'counting_channel' : {'$exists' : True}}).get('counting_channel'))
        except:
            await channel.send('You must set a counting channel using **$link counting** ***#channel***.')
            return
        now = datetime.utcnow()
        interval = 'Daily'
        if len(args) >= 1:
            if args[0] == 'daily':
                td = timedelta(days=1)
                interval = 'Daily'
            elif args[0] == 'weekly':
                td = timedelta(weeks=1)
                interval = 'Weekly'
            elif args[0] == 'monthly':
                td = timedelta(weeks=4)
                interval = 'Monthly'
            elif args[0] == 'all':
                oldest_mesg = await counting_channel.history(limit=1, oldest_first=True).flatten()
                td = now - oldest_mesg[0].created_at    
                interval = "All Time"
            else:
                await channel.send("Something went wrong. Try running this command again. You must specify **weekly**, **monthly**, or **all**, or just **#leaderboard** for all time.")
                return
        else:
            td = timedelta(days=1)
            interval = 'Daily'
    
        now = datetime.utcnow()
        slowmode = counting_channel.slowmode_delay
        counting_channel_history = await counting_channel.history(limit=None).flatten()

        ranks_and_efficiency = await calculate_member_stats(guild.members, None, counting_channel_history, slowmode, now - td)

        embed = discord.Embed(color=0x3498db)
        embed.add_field(name=f'{interval} Leaderboard 💯', value='___', inline=False)

        for i in range(min(6, len(ranks_and_efficiency))):
            place = i+1
            if place == 1:
                place = ":first_place:"
            elif place == 2:
                place = ":second_place:"
            elif place == 3:
                place = ":third_place:"
            embed.add_field(name=f"***{place}*** - {ranks_and_efficiency[i][1].display_name}", value=f"{await efficiency_bar(ranks_and_efficiency[i][2])} ({ranks_and_efficiency[i][2]}%)", inline=False)
        await channel.send(embed=embed)



@bot.command()
async def stats(ctx, member : discord.Member = None):
    member = member or ctx.author 
    async with ctx.channel.typing():
        collection = db[str(ctx.guild.id)]
        counting_channel = bot.get_channel((collection.find_one({'counting_channel' : {'$exists' : True}}) or {0:0}).get('counting_channel'))
        if counting_channel is None:
            await ctx.send('You must set a counting channel using **$link counting** ***#channel***.')
            return

        now = datetime.utcnow()
        slowmode = counting_channel.slowmode_delay
        counting_channel_history = await counting_channel.history(limit=None, oldest_first=True).flatten()

        # returns in format: [member, rank, efficiency]
        daily_stats = await calculate_member_stats(ctx.guild.members, member, counting_channel_history, slowmode, now - timedelta(days=1))
        prev_daily_stats = await calculate_member_stats(ctx.guild.members, member, counting_channel_history, slowmode, now - timedelta(days=2), now - timedelta(days=1))
        weekly_stats = await calculate_member_stats(ctx.guild.members, member, counting_channel_history, slowmode, now - timedelta(weeks=1))
        prev_weekly_stats = await calculate_member_stats(ctx.guild.members, member, counting_channel_history, slowmode, now - timedelta(weeks=2), now - timedelta(weeks=1))

        monthly_stats = await calculate_member_stats(ctx.guild.members, member, counting_channel_history, slowmode, now - timedelta(weeks=4))
        prev_monthly_stats = await calculate_member_stats(ctx.guild.members, member, counting_channel_history, slowmode, now - timedelta(weeks=8), now - timedelta(weeks=4))

        oldest_time = counting_channel_history[0].created_at
        all_time = await calculate_member_stats(ctx.guild.members, member, counting_channel_history, slowmode, oldest_time)

        embed = discord.Embed(color=member.color)
        embed.set_author(name=member.name+"'s stats", icon_url=member.avatar_url)
        embed.set_footer(text="Counted a total of " + str(all_time[3]) + " times.")

        daily_direction = 'Up' if daily_stats[2] > prev_daily_stats[2] else 'Down'
        daily_bar = await efficiency_bar(daily_stats[2]) + f" ({daily_stats[2]}%)"+f"\n```{daily_direction} {abs(round(daily_stats[2]-prev_daily_stats[2], 1))}% from yesterday```"
        embed.add_field(name="Daily - Ranked #"+str(daily_stats[1]), value=daily_bar)

        weekly_direction = 'Up' if weekly_stats[2] > prev_weekly_stats[2] else 'Down'
        weekly_bar = await efficiency_bar(weekly_stats[2]) + f" ({weekly_stats[2]}%)"+f"\n```{weekly_direction} {abs(round(weekly_stats[2]-prev_weekly_stats[2], 1))}% from last week```"
        embed.add_field(name='Weekly - Ranked #'+str(weekly_stats[1]), value=weekly_bar)

        monthly_direction = 'Up' if monthly_stats[2] > prev_monthly_stats[2] else 'Down'
        monthly_bar = await efficiency_bar(monthly_stats[2]) + f" ({monthly_stats[2]}%)"+f"\n```{monthly_direction} {abs(round( monthly_stats[2]-prev_monthly_stats[2], 1))}% from last month```"
        embed.add_field(name='Monthly - Ranked #'+str(monthly_stats[1]), value=monthly_bar)

        await ctx.send(embed=embed)
@stats.error 
async def stats_error(ctx, error):
    if isinstance(error, commands.BadArgument):
        await ctx.send("That member doesn't exist...")

@bot.command()
async def story(ctx, arg : int = 1):
    async with ctx.channel.typing():
        collection = db[str(ctx.guild.id)]
        story_channel = bot.get_channel((collection.find_one({'onewordstory_channel' : {'$exists' : True}}) or {0:0}).get('onewordstory_channel'))
        if story_channel is None:
            await ctx.send('You must set a onewordstory channel using **$link onewordstory** ***#channel***.')
            return

        text = ''
        async for message in story_channel.history(limit=None, oldest_first=True):
            if not message.attachments:
                text += message.content + ' '
            else: 
                text += '$asdf$'

        text = "The " + text.split('$asdf$')[arg]
        for line in textwrap.wrap(text, width=2000):
            await ctx.send(line)

@bot.command()
@commands.check(is_admin)
async def stop_the_count(ctx):
    collection = db[str(ctx.guild.id)]
    collection.replace_one({"disable_counting" : {'$exists' : True}}, {"disable_counting" : True}, upsert=True)
    await ctx.send('I will now stop counting...')

@bot.command()
async def start_counting(ctx):        
    collection = db[str(ctx.guild.id)]
    collection.replace_one({"disable_counting" : {'$exists' : True}}, {"disable_counting" : False}, upsert=True)
    await ctx.send('I will now begin counting...')



@bot.command()
async def length(ctx, member : discord.Member = None):
    member = member or ctx.author
    length = round(member.id / 10**17, 1)

    if member.id == 184880932476420097:
        length = 7
    elif member.id == 495824425711828993:
        length = 11.1

    await ctx.send(f"{member.mention}'s cock length is {length} inches.")
        
        


### FUNCTIONS
async def sleep_until_hour(hour_utc : int):
    now = datetime.utcnow()
    if now.hour != hour_utc or now.minute != 0:
        if now.hour < hour_utc:
            wait_until = now.replace(hour=hour_utc, minute=0, second=0, microsecond=0)
            await asyncio.sleep((wait_until - now).total_seconds())
        else:
            wait_until = now.replace(day=now.day+1, hour=hour_utc, minute=0, second=0, microsecond=0)
            await asyncio.sleep((wait_until - now).total_seconds())

async def calculate_member_stats(members, req_member, channel_history, slowmode_delay, after, before=None):
    if before is None:
        before = datetime.utcnow()

    channel_history = [x for x in channel_history if x.created_at > after and x.created_at < before]
    # .slowmode_delay is in seconds
    possible_counts_interval = round((before - after).total_seconds() / slowmode_delay)

    stats = []
    for member in members:
        counter = 0
        for message in channel_history:
            if message.author == member:
                counter +=1
        stats.append([member, round(counter / possible_counts_interval * 100, 2), counter])

    # sort efficiencies low to high
    efficiency_stats = sorted(stats, key=lambda x: x[1], reverse=True)

    # if req_member is set to None, then return all stats, sorted
    if req_member is None:
        ranks_and_efficiency = []
        for i in range(len(efficiency_stats)):
            # returns in format [ [rank, member, efficiency, total_counts], [], [] ]
            ranks_and_efficiency.append([i+1, efficiency_stats[i][0], efficiency_stats[i][1], efficiency_stats[i][2]])
        return ranks_and_efficiency
    else:
        for i,e in enumerate(efficiency_stats):
            if e[0] == req_member:
                # format: [member, rank, efficiency, total_counts]
                return [e[0], i+1, e[1], e[2]]

async def efficiency_bar(percent: float) -> str:
    """Returns a string of 10 full and empty squares representing the percent variable, where percent is a float > 0."""
    percent = round(percent/10)
    return '[■](https://youtu.be/dQw4w9WgXcQ)'*min(10, percent) + '[□](https://youtu.be/dQw4w9WgXcQ)'*(10-percent)




### RUN
bot.run(token)
