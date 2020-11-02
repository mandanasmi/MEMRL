## write an example agent and show that it does stuff
import gym
import Networks as nets
import EpisodicMemory as ec
from basic.Agents import Agent
import torch
import numpy as np

class basic_agent_params():
    def __init__(self, env):
        self.load_model = False
        self.load_dir   = ''
        self.architecture = 'A'
        self.input_dims = env.observation.shape
        self.action_dims = 4
        self.hidden_types = ['conv', 'pool', 'conv', 'pool', 'linear', 'linear']
        self.hidden_dims = [None, None, None, None, 1000, 1000]
        self.freeze_w = False
        self.rfsize = 5
        self.gamma = 0.98
        self.eta = 5e-4


env = gym.make('gym_grid:gridworld-v1')

agent_params = basic_agent_params(env)

network = nets.ActorCritic(agent_params.__dict__)
memory = ec.EpisodicMemory(6, 400)
attempt = Agent(network, memory)


def get_action(s):
    attempt.select_action(s)

maxsteps = 100
for step in range(maxsteps):
    s = torch.Tensor(np.expand_dims(env.get_observation(), axis=0))

    action = get_action(s)
    print(action)

    s_prime, r, done, __ = env.step(action)

    print(s, action, s_prime, r)

    env.render(0.05)

    if step == maxsteps - 1 or done:
        plt.show(block=True)

    if done:
        break

