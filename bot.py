import discord
import logging 
import os
import json
import asyncio
import inflect
import textwrap
import traceback
from re import sub, compile
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
db = db_client["botsky"]

with open('questions.json') as f:
    questions = json.load(f)
with open('activities.json') as f:
    activities = json.load(f)

## EVENTS
@bot.event
async def on_ready():
    logging.info(f'{bot.user.name} has connected to Discord!')
    change_presense.start()
    weekly_leaderboard.start()
    floppa_friday.start()

async def is_admin(ctx):
    return ctx.author.guild_permissions.administrator or ctx.author.id == 184880932476420097




### TASKS
@tasks.loop(minutes=15)
async def change_presense():
    activity = discord.Game(choice(activities))
    await bot.change_presence(activity=activity)

@tasks.loop(hours=24*7)
async def weekly_leaderboard():  
    # trigger every synday at 20:00 PST --- server is now in PST
    # there has to be a more efficient way to do this
    await sleep_until_hour(20)
    while datetime.now().weekday() != 6:
        await asyncio.sleep(24 * 60 * 60)
    for guild in bot.guilds:
        collection = db[str(guild.id)]
        try: 
            announcements_channel = bot.get_channel(collection.find_one({"channel" : "announcements"}).get("snowflake"))
        except: 
            return
        if not announcements_channel: return
        await leaderboard_print(announcements_channel, guild, 'weekly')

@tasks.loop(hours=24*7)
async def floppa_friday():
    # there has to be a more efficient way to do this
    # trigger every sunday at 20:00 PST
    await sleep_until_hour(20)
    while datetime.now().weekday() != 6:
        await asyncio.sleep(24 * 60 * 60)
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
    if message.author.bot:
        return

    collection = db[str(message.guild.id)]
    try: 
        counting_channel = bot.get_channel(collection.find_one({"channel" : "counting"}).get("snowflake"))
    except: 
        counting_channel = None

    p = inflect.engine()
    # check if someone counted incorrectly in the counting channel
    if message.channel == counting_channel:
        latest_mesgs = [x for x in await counting_channel.history(limit=4).flatten() if "you've counted incorrectly" not in x.content.lower()]
        try: 
            latest_count = int(sub("[^0-9]", "", latest_mesgs[0].content))
            latest_count_2 = int(sub("[^0-9]", "", latest_mesgs[1].content))
        except: 
            latest_count, latest_count_2 = 0, 0
        if latest_count != latest_count_2 + 1:
            mistakes = (collection.find_one({"member" : message.author.id}) or {0:0}).get("mistakes", 0) + 1
            collection.update_one({"member" : message.author.id}, {"$inc" : {"mistakes" : 1}}, upsert=True)
            mesg = message.author.mention + " You've counted incorrectly. This is your " + p.ordinal(mistakes) + " mistake. Please fix your number."
            await counting_channel.send(mesg, delete_after=10)
    elif not message.content.startswith(".") and not message.content.startswith("$") and 'c' in message.content.lower() and not _match_url(message.content):
        # if message contains c
        # if 'OUT' in [x.name for x in message.author.roles]:
        #         return
        # collection = db[str(message.guild.id)]
        # current_strikes = (collection.find_one({"member" : message.author.id}) or {0:0}).get("strikes", 0) + 1

        # if current_strikes < 3:
        #     collection.update_one({"member" : message.author.id}, {"$set" : {"strikes" : current_strikes}}, upsert=True)
        #     await message.channel.send(f'{message.author.mention} You have used a forbidden letter. That was your {p.ordinal(current_strikes)} strike.')
        # else: 
        #     await message.channel.send(f"{message.author.mention} That was your 3rd strike. You are out. I'm putting you on timeout for an hour.")
        #     out = get(message.guild.roles, name = 'OUT')
        #     await message.author.add_roles(out)
        #     collection.update_one({"member" : message.author.id}, {"$set" : {"strikes" : 0}})
        #     collection.update_one({"member" : message.author.id}, {"$inc" : {"strikeouts" : 1}})
        #     await asyncio.sleep(60 * 60)
        #     await message.author.remove_roles(out)
    else:
        if 'tuesday' in message.content.lower():
            await message.channel.send(file=discord.File('tueday.png'))
        # 2% chance of sending a random message
        if random() < 0.003:
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
    current_strikes = (collection.find_one({"member" : member.id}) or {0:0}).get("strikes", 0)
    await ctx.channel.send(f"{member.mention} has {current_strikes} strikes.")

@bot.command()
async def strikeouts(ctx, member : discord.Member = None):
    member = member or ctx.author 
    collection = db[str(ctx.guild.id)]
    current_strikeouts = (collection.find_one({"member" : member.id}) or {0:0}).get("strikeouts", 0)
    if current_strikeouts == 1:
        await ctx.channel.send(f"{member.mention} has {current_strikeouts} strikeout.")
    else:
        await ctx.channel.send(f"{member.mention} has {current_strikeouts} strikeouts.")

@bot.command()
@commands.check(is_admin)
async def link(ctx, category : str, channel : discord.TextChannel):
    channel_types = ['counting', 'announcements']
    if category not in channel_types:
        raise commands.BadArgument
    collection = db[str(ctx.guild.id)]
    collection.replace_one({"channel" : category}, {"channel" : category, "snowflake" : channel.id}, upsert=True)
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
        collection = db[str(guild.id)]
        try: 
            counting_channel = bot.get_channel(collection.find_one({"channel" : "counting"}).get("snowflake"))
            if not counting_channel:
                await no_channel_set(channel, "counting")
        except:
            await no_channel_set(channel, "counting")
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
        try: 
            counting_channel = bot.get_channel(collection.find_one({"channel" : "counting"}).get("snowflake"))
            if not counting_channel:
                await no_channel_set(ctx.channel, "counting")
                return
        except:
            await no_channel_set(ctx.channel, "counting")
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
async def length(ctx, member : discord.Member = None):
    member = member or ctx.author
    length = round(member.id / 10**17, 1)

    if member.id == 184880932476420097:
        length = 7
    elif member.id == 495824425711828993:
        length = 11.1

    await ctx.send(f"{member.mention}'s cock length is {length} inches.")
        
        


### FUNCTIONS
async def no_channel_set(channel, category):
    if category == "counting":
        await channel.send('You must set a counting channel using **$link counting** ***#channel***.')
    elif category == "announcements":
        await channel.send('You must set an announcements channel using **$link announcements** ***#channel***.')

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

def _match_url(url):
    """from https://stackoverflow.com/questions/58211619/how-to-check-for-hyperlinks-in-the-contents-of-a-message-through-discord-py-pre
    """
    regex = compile(
        r"(([\w]+:)?//)?(([\d\w]|%[a-fA-f\d]{2,2})+(:([\d\w]|%[a-fA-f\d]{2,2})+)?@)?([\d\w][-\d\w]{0,253}[\d\w]\.)+[\w]{2,63}(:[\d]+)?(/([-+_~.\d\w]|%[a-fA-f\d]{2,2})*)*(\?(&?([-+_~.\d\w]|%[a-fA-f\d]{2,2})=?)*)?(#([-+_~.\d\w]|%[a-fA-f\d]{2,2})*)?"
    )
    if regex.match(url):
        return True
    else:
        return False


### RUN
bot.run(token)
