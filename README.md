# Pwnagotchi project with AI/ML

<p align="center">
    <a href="https://github.com/nvmd/pwnagotchi/releases/latest"><img alt="Release" src="https://img.shields.io/github/release/nvmd/pwnagotchi.svg?style=flat-square"></a>
    <a href="https://github.com/nvmd/pwnagotchi/blob/master/LICENSE.md"><img alt="Software License" src="https://img.shields.io/badge/license-GPL3-brightgreen.svg?style=flat-square"></a>
    <a href="https://github.com/nvmd/pwnagotchi/graphs/contributors"><img alt="Contributors" src="https://img.shields.io/github/contributors/nvmd/pwnagotchi?style=flat-square"/></a>
</p>

This fork is maintaining and improving upon the original vision for Pwnagotchi as an engaging toy with "AI" personality.

The goal is to implement numerous long overdue improvements throughout the codebase to increase maintainability, hackability and its potential as a powerful _learning toy_ for machine learning and wireless networks.


# Hello, I'm [Pwnagotchi](https://pwnagotchi.org/)!

![ui](https://i.imgur.com/X68GXrn.png)

an [A2C](https://hackernoon.com/intuitive-rl-intro-to-advantage-actor-critic-a2c-4ff545978752)-based "AI" leveraging [bettercap](https://www.bettercap.org/) that learns from its surrounding Wi-Fi environment to maximize the crackable WPA key material it captures (either passively, or by performing authentication and association attacks).

This material is collected as PCAP files containing any form of handshake supported by [hashcat](https://hashcat.net/hashcat/), including [PMKIDs](https://www.evilsocket.net/2019/02/13/Pwning-WiFi-networks-with-bettercap-and-the-PMKID-client-less-attack/), 
full and half WPA handshakes.

## AI

Instead of merely playing [Super Mario or Atari games](https://becominghuman.ai/getting-mario-back-into-the-gym-setting-up-super-mario-bros-in-openais-gym-8e39a96c1e41?gi=c4b66c3d5ced) like most reinforcement learning-based "AI" *(yawn)*, Pwnagotchi tunes [its parameters](https://github.com/evilsocket/pwnagotchi/blob/master/pwnagotchi/defaults.toml) over time to **get better at pwning Wi-Fi things to** in the environments you expose it to. 

More specifically, Pwnagotchi is using an [LSTM with MLP feature extractor](https://stable-baselines.readthedocs.io/en/master/modules/policies.html#stable_baselines.common.policies.MlpLstmPolicy) as its policy network for the [A2C agent](https://stable-baselines.readthedocs.io/en/master/modules/a2c.html). If you're unfamiliar with A2C, here is [a very good introductory explanation](https://hackernoon.com/intuitive-rl-intro-to-advantage-actor-critic-a2c-4ff545978752) (in comic form!) of the basic principles behind how Pwnagotchi learns. (You can read more about how Pwnagotchi learns in the [Usage](https://www.pwnagotchi.ai/usage/#training-the-ai) doc.)

**Keep in mind:** Unlike the usual RL simulations, Pwnagotchi learns over time. Time for a Pwnagotchi is measured in epochs; a single epoch can last from a few seconds to minutes, depending on how many access points and client stations are visible. Do not expect your Pwnagotchi to perform amazingly well at the very beginning, as it will be [exploring](https://hackernoon.com/intuitive-rl-intro-to-advantage-actor-critic-a2c-4ff545978752) several combinations of [key parameters](https://www.pwnagotchi.ai/usage/#training-the-ai) to determine ideal adjustments for pwning the particular environment you are exposing it to during its beginning epochs ... but ** listen to your Pwnagotchi when it tells you it's boring!** Bring it into novel Wi-Fi environments with you and have it observe new networks and capture new handshakes—and you'll see. :)

## Peering

Multiple units within close physical proximity can "talk" to each other, advertising their presence to each other by broadcasting custom information elements using a parasite protocol I've built on top of the existing dot11 standard. Over time, two or more units trained together will learn to cooperate upon detecting each other's presence by dividing the available channels among them for optimal pwnage.

## Documentation

* https://pwnagotchi.org
* https://github.com/jayofelony/pwnagotchi/wiki

## Links

| &nbsp;    | Official Links                                              |
|-----------|-------------------------------------------------------------|
| Website   | [pwnagotchi.org](https://pwnagotchi.org/)                     |
| Forum     | [discord.gg](https://discord.gg/PGgnzFbz4M) |
| Subreddit | [r/pwnagotchi](https://www.reddit.com/r/pwnagotchi/)        |

## License

`pwnagotchi` created by [@evilsocket](https://twitter.com/evilsocket) and [contributors](https://github.com/nvmd/pwnagotchi/graphs/contributors). Released under the terms of the GPLv3 license.
