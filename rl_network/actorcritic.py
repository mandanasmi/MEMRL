#### Model Free Agent 

'''
Object Classes and Relevant Functions for Actor Critic Agent
Author: Annik Carson 
--  Oct 2019
'''

# =====================================
#           IMPORT MODULES            #
# =====================================
from __future__ import division, print_function

import numpy as np

import torch 
from torch.autograd import Variable
from torch import autograd, optim, nn
import torch.nn.functional as F
from torch.distributions import Categorical

from collections import namedtuple

import stategen as sg

# =====================================
# CLASSES
# =====================================
# Network Class
class AC_Net(nn.Module):
	'''
	An actor-critic neural network class. Takes sensory inputs and generates a policy and a value estimate.
	'''

	# ================================
	def __init__(self, agent_params, **kwargs):
		input_dimensions  = kwargs.get('input_dimensions', agent_params['input_dims'])
		action_dimensions = kwargs.get('action_dimensions', agent_params['action_dims'])
		batch_size        = kwargs.get('batch_size', 4)
		hidden_types      = kwargs.get('hidden_types', agent_params['hid_types'])
		hidden_dimensions = kwargs.get('hidden_dimensions', agent_params['hid_dims'])
		rfsize            = kwargs.get('rfsize', 4)
		padding           = kwargs.get('padding', 1)
		stride            = kwargs.get('stride', 1)
		
		'''
		def __init__(self, input_dimensions, action_dimensions, 
		batch_size=4, hidden_types=[], hidden_dimensions=[],
		rfsize=4, padding=1, stride=1):
		
		AC_Net(input_dimensions, action_dimensions, hidden_types=[], hidden_dimensions=[])

		Create an actor-critic network class.

		Required arguments:
			- input_dimensions (int): the dimensions of the input space
			- action_dimensions (int): the number of possible actions

		Optional arguments:
			- batch_size (int): the size of the batches (default = 4).
			- hidden_types (list of strings): the type of hidden layers to use, options are 'linear',
											  'lstm', 'gru'. If list is empty no hidden layers are
											  used (default = []).
			- hidden_dimensions (list of ints): the dimensions of the hidden layers. Must be a list of
												equal length to hidden_types (default = []).
			- TODO insert new args
		'''
	   
		# call the super-class init 
		super(AC_Net, self).__init__()

		# store the input dimensions
		self.input_d = input_dimensions
		# determine input type
		if type(input_dimensions) == int:
			assert (hidden_types[0] == 'linear' or hidden_types[0] == 'lstm' or hidden_types[0] == 'gru')
			self.input_type = 'vector'
		elif type(input_dimensions) == tuple:
			assert (hidden_types[0] == 'conv' or hidden_types[0] == 'pool')
			self.input_type = 'frame'

		# store the batch size
		self.batch_size = batch_size

		# check that the correct number of hidden dimensions are specified
		assert len(hidden_types) is len(hidden_dimensions)
		
		# check whether we're using hidden layers
		if not hidden_types:

			self.layers = [input_dimensions,action_dimensions]

			# no hidden layers, only input to output, create the actor and critic layers
			self.output = nn.ModuleList([
				nn.Linear(input_dimensions, action_dimensions), # ACTOR
				nn.Linear(input_dimensions, 1)])				# CRITIC
		else:
			# to store a record of the last hidden states
			self.hx = []
			self.cx = []
		
			# create the hidden layers
			self.hidden = nn.ModuleList()
			for i,htype in enumerate(hidden_types):
				
				# check that the type is an accepted one
				assert htype in ['linear','lstm','gru', 'conv', 'pool']

				# get the input dimensions
				if i is 0:
					input_d  = input_dimensions
				else:
					if hidden_types[i-1] in ['conv','pool'] and not htype in ['conv','pool']:
						input_d = int(np.prod(hidden_dimensions[i-1]))
					else:
						input_d = hidden_dimensions[i-1]

				# get the output dimensions
				if not htype in ['conv','pool']:
					output_d = hidden_dimensions[i]
				elif htype in ['conv','pool']:
					output_d = list((0,0,0))
					if htype is 'conv':
						output_d[0] = int(np.floor((input_d[0] + 2*padding - rfsize)/stride) + 1)
						output_d[1] = int(np.floor((input_d[1] + 2*padding - rfsize)/stride) + 1)
						assert output_d[0] == hidden_dimensions[i][0], (hidden_dimensions[i][0], output_d[0])
						assert output_d[1] == hidden_dimensions[i][1]
						output_d[2] = hidden_dimensions[i][2]
					elif htype is 'pool':
						output_d[0] = int(np.floor((input_d[0] +2*padding - (rfsize-1) -1)/stride  +1 ))
						output_d[1] = int(np.floor((input_d[0] +2*padding - (rfsize-1) -1)/stride  +1 ))
						assert output_d[0] == hidden_dimensions[i][0]
						assert output_d[1] == hidden_dimensions[i][1]
						output_d[2] = hidden_dimensions[i][2]
					output_d = tuple(output_d)
				
				# construct the layer
				if htype is 'linear':
					self.hidden.append(nn.Linear(input_d, output_d))
					self.hx.append(None)
					self.cx.append(None)
				elif htype is 'lstm':
					self.hidden.append(nn.LSTMCell(input_d, output_d))
					self.hx.append(Variable(torch.zeros(self.batch_size,output_d)))
					self.cx.append(Variable(torch.zeros(self.batch_size,output_d)))
				elif htype is 'gru':
					self.hidden.append(nn.GRUCell(input_d, output_d))
					self.hx.append(Variable(torch.zeros(self.batch_size,output_d)))
					self.cx.append(None)
				elif htype is 'conv':
					self.hidden.append(nn.Conv2d(input_d[2],output_d[2],rfsize,padding=padding,stride=stride))
					self.hx.append(None)
					self.cx.append(None)
				elif htype is 'pool':
					self.hidden.append(nn.MaxPool2d(rfsize,padding=padding,stride=stride))
					self.hx.append(None)
					self.cx.append(None)

			# create the actor and critic layers
			self.layers = [input_dimensions]+hidden_dimensions+[action_dimensions]
			self.output = nn.ModuleList([
				nn.Linear(output_d, action_dimensions), #actor
				nn.Linear(output_d, 1)                  #critic
			])
		# store the output dimensions
		self.output_d = output_d

		# to store a record of actions and rewards	
		self.saved_actions = []
		self.rewards = []


	# ================================
	def forward(self, x, temperature=1):
		'''
		forward(x):

		Runs a forward pass through the network to get a policy and value.

		Required arguments:
			- x (torch.Tensor): sensory input to the network, should be of size batch x input_d
		'''

		# check the inputs
		if type(self.input_d) == int:
			assert x.shape[-1] == self.input_d
		elif type(self.input_d) == tuple:
			assert (x.shape[2], x.shape[3], x.shape[1]) == self.input_d
			if not  (isinstance(self.hidden[0],nn.Conv2d) or isinstance(self.hidden[0],nn.MaxPool2d)):
				raise Exception('image to non {} layer'.format(self.hidden[0]))

		# pass the data through each hidden layer
		for i, layer in enumerate(self.hidden):
			# squeeze if last layer was conv/pool and this isn't
			if i > 0:
				if (isinstance(self.hidden[i-1],nn.Conv2d) or isinstance(self.hidden[i-1],nn.MaxPool2d)) and \
				not (isinstance(layer,nn.Conv2d) or isinstance(layer,nn.MaxPool2d)):
					x = x.view(1, -1)
			# run input through the layer depending on type
			if isinstance(layer, nn.Linear):
				x = F.relu(layer(x))
				lin_activity = x
			elif isinstance(layer, nn.LSTMCell):
				x, cx = layer(x, (self.hx[i], self.cx[i]))
				self.hx[i] = x.clone()
				self.cx[i] = cx.clone()
			elif isinstance(layer, nn.GRUCell):
				x = layer(x, self.hx[i])
				self.hx[i] = x.clone()
			elif isinstance(layer, nn.Conv2d):
				x = F.relu(layer(x))
			elif isinstance(layer, nn.MaxPool2d):
				x = layer(x)
		# pass to the output layers
		policy = F.softmax(self.output[0](x), dim=1)
		value  = self.output[1](x)
		
		if isinstance(self.hidden[-1], nn.Linear):
			return policy, value, lin_activity
		else:
			return policy, value

	# ===============================
	def reinit_hid(self):
		# to store a record of the last hidden states
		self.hx = []
		self.cx = []
	
		for i, layer in enumerate(self.hidden):
			if isinstance(layer, nn.Linear):
				pass
			elif isinstance(layer, nn.LSTMCell):
				self.hx.append(Variable(torch.zeros(self.batch_size,layer.hidden_size)))
				self.cx.append(Variable(torch.zeros(self.batch_size,layer.hidden_size)))
			elif isinstance(layer, nn.GRUCell):
				self.hx.append(Variable(torch.zeros(self.batch_size,layer.hidden_size)))
				self.cx.append(None)
			elif isinstance(layer, nn.Conv2d):
				pass
			elif isinstance(layer, nn.MaxPool2d):
				pass

	#def calc_conv_dims(self, )

def conv_output(input_tuple, **kwargs): 
	h_in, w_in, channels = input_tuple
	padding = kwargs.get('padding', 1) ## because this is 1 in MF, default 0
	dilation = kwargs.get('dilation', 1) # default 1
	kernel_size = kwargs.get('rfsize', 4 ) # set in MF
	stride = kwargs.get('stride', 1) # set in MF, default 1 
	
	h_out = int(np.floor(((h_in +2*padding - dilation*(kernel_size-1) - 1)/stride)+1))
	w_out = int(np.floor(((w_in +2*padding - dilation*(kernel_size-1) - 1)/stride)+1))
	
	return (h_out, w_out, channels)


# =====================================
# FUNCTIONS FOR STATE INPUT GENERATION
# =====================================
# Place cell activity vector 

# Gridworld frame tensor 



# =====================================
# FUNCTIONS FOR END OF TRIAL
# =====================================
SavedAction = namedtuple('SavedAction', ['log_prob', 'value'])

def select_action(model,policy_, value_):
	a = Categorical(policy_)
	action = a.sample()
	model.saved_actions.append(SavedAction(a.log_prob(action), value_))
	
	return action.item(), policy_.data[0], value_.item()


def select_ec_action(model, mf_policy_, mf_value_, ec_policy_):
	a = Categorical(ec_policy_)
	b = Categorical(mf_policy_)
	action = a.sample()
	model.saved_actions.append(SavedAction(b.log_prob(action), mf_value_))

	return action.item(), mf_policy_.data[0], mf_value_.item()


# Functions for computing relevant terms for weight updates after trial runs
def finish_trial(model, discount_factor, optimizer, **kwargs):
	'''
	finish_trial(model
	Finishes a given training trial and backpropagates.
	'''

	# set the return to zero
	R = 0
	returns_ = discount_rwds(np.asarray(model.rewards), gamma=discount_factor)
	saved_actions = model.saved_actions
	
	policy_losses = []
	value_losses = []
	
	returns_ = torch.Tensor(returns_)

	EC = kwargs.get('cache', None)
	memory_buffer = kwargs.get('buffer', None)

	if EC is not None:
		if memory_buffer is not None:
			timesteps = memory_buffer[0]
			states    = memory_buffer[1]
			actions   = memory_buffer[2]
			readable  = memory_buffer[3]
			trial 	  = memory_buffer[4]
			mem_dict  = {}
		else:
			raise Exception('No memory buffer provided for kwarg "buffer=" ')
		for (log_prob, value), r, t_, s_, a_, rdbl in zip(saved_actions, returns_, timesteps, states, actions, readable):
			rpe = r - value.item()
			policy_losses.append(-log_prob * rpe)
			value_losses.append(F.smooth_l1_loss(value, Variable(torch.Tensor([[r]]))).unsqueeze(-1))

			mem_dict['activity'] = s_
			mem_dict['action']   = a_
			mem_dict['delta']    = rpe.item()
			mem_dict['timestamp']= t_
			mem_dict['readable'] = rdbl
			mem_dict['trial']    = trial
			#print(f"agent at {rdbl}: takes action {a_}, delta: {rpe.item()} ({r} - {value.item()})" )
			EC.add_mem(mem_dict)

	else:
		for (log_prob, value), r in zip(saved_actions, returns_):
			rpe = r - value.item()
			policy_losses.append(-log_prob * rpe)
			value_losses.append(F.smooth_l1_loss(value, Variable(torch.Tensor([[r]]))).unsqueeze(-1))
			#value_losses.append(F.mse_loss(value, Variable(torch.Tensor([[r]]))))
	optimizer.zero_grad()

	p_loss = (torch.cat(policy_losses).sum())
	v_loss = (torch.cat(value_losses).sum())

	total_loss = p_loss + v_loss

	total_loss.backward(retain_graph=False)
	optimizer.step()

	del model.rewards[:]
	del model.saved_actions[:]

	return p_loss, v_loss

def discount_rwds(r, gamma = 0.99): 
	disc_rwds = np.zeros_like(r)
	running_add = 0
	for t in reversed(range(0, r.size)): 
		running_add = running_add*gamma + r[t]
		disc_rwds[t] = running_add
	return disc_rwds

def generate_values(maze, model):
	value_map = maze.empty_map

	for loc in maze.useable:
		state = Variable(torch.FloatTensor(sg.get_frame(maze,agtlocation=loc)))
		policy, value = sample_select_action(model,state)[1:3]
		value_map[loc[1]][loc[0]] = value
		
	return value_map
	
def generate_values_old(maze, model,**kwargs):
	value_map = maze.empty_map
	EC = kwargs.get('EC', None)
	pcs = kwargs.get('pcs', None)
	if EC!=None:
		EC_pol_map = maze.make_map(maze.grid, pol=True)
		MF_pol_map = maze.make_map(maze.grid, pol=True)
	for loc in maze.useable:
		if model.input_type == 'vector':
			state = Variable(torch.FloatTensor(pcs.activity(loc)))
			policy, value = sample_select_action(model,state)[1:3]
		
		elif model.input_type == 'frame':
			state = Variable(torch.FloatTensor(sg.get_frame(maze,agtlocation=loc)))
			if isinstance (model.hidden[-1], nn.Linear):
				policy, value, lin_act = sample_select_action(model,state, getlin=True)[1:4]
			else: 
				policy, value = sample_select_action(model,state)[1:3]
		
		value_map[loc[1]][loc[0]] = value
		if EC != None:
			if model.input_type == 'vector':
				EC_pol = EC.recall_mem(tuple(state.data[0]))
			elif model.input_type == 'frame':
				EC_pol = EC.recall_mem(tuple(lin_act.view(-1)))
			EC_pol_map[loc[1]][loc[0]] = tuple(EC_pol.data[0])
			MF_pol_map[loc[1]][loc[0]] = tuple(policy)

	if EC == None:
		return value_map
	else:
		return EC_pol_map, MF_pol_map
	
def make_agent(agent_params, freeze=False):
	if agent_params['load_model']: 
		MF = torch.load(agent_params['load_dir']) # load previously saved model
	else:
		MF = AC_Net(agent_params)

	if freeze:

		freeze = []
		unfreeze = []
		for i, nums in MF.named_parameters():
			if i[0:6] == 'output':
				unfreeze.append(nums)
			else:
				freeze.append(nums)

		opt = optim.Adam([{'params': freeze, 'lr': 0.0}, {'params': unfreeze, 'lr': agent_params['eta']}], lr=0.0)
	else:
		critic = []
		others = []
		for i, nums in MF.named_parameters():
			if i[0:8] == 'output.1': #critic
				critic.append(nums)
			else:
				others.append(nums)
		opt = optim.Adam(MF.parameters(), lr= agent_params['eta'])
	return MF, opt


def snapshot(maze, agent):
	val_array = np.empty(maze.grid.shape)
	pol_array = np.zeros(maze.grid.shape, dtype=[('N', 'f8'), ('E', 'f8'), ('W', 'f8'), ('S', 'f8'), ('stay', 'f8'), ('poke', 'f8')])
	# cycle through all available states
	for i in maze.useable:
		maze.cur_state = i
		state = torch.Tensor(sg.get_frame(maze))
		policy_, value_ = agent(state)[0:2]

		val_array[i[1], i[0]] = value_.item()
		pol_array[i[1], i[0]] = tuple(policy_.detach().numpy()[0])

	return val_array, pol_array

def mem_snapshot(maze, EC, trial_timestamp,**kwargs):
	envelope = kwargs.get('decay', 50)
	mpol_array = np.zeros(maze.grid.shape, dtype=[('N', 'f8'), ('E', 'f8'), ('W', 'f8'), ('S', 'f8'), ('stay', 'f8'), ('poke', 'f8')])
	# cycle through readable states
	for i in EC.cache_list.values():
		xval = i[2][0]
		yval = i[2][1]

		memory       = np.nan_to_num(i[0])
		deltas       = memory[:,0]
		times        = abs(trial_timestamp - memory[:,1])
		pvals 		 = EC.make_pvals(times, envelope=envelope)

		policy = softmax(  np.multiply(deltas, pvals), T=1) #np.multiply(sim,deltas))
		mpol_array[yval][xval] = tuple(policy)
	return mpol_array

def softmax(x, T=1):
	e_x = np.exp((x - np.max(x))/T)
	return np.round(e_x / e_x.sum(axis=0),8) # only difference
