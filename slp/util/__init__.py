import torch

from slp.util import system as _sysutil
from slp.util import log


LOGGER = log.getLogger('default')


def to_device(tt, device='cpu', non_blocking=False):
    return tt.to(device, non_blocking=non_blocking)


def t_(data, dtype=torch.float, device='cpu', requires_grad=False):
    """Convert a list or numpy array to torch tensor. If a torch tensor
    is passed it is cast to  dtype, device and the requires_grad flag is
    set IN PLACE.

    Args:
        data: (list, np.ndarray, torch.Tensor): Data to be converted to
            torch tensor.
        dtype: (torch.dtype): The type of the tensor elements
            (Default value = torch.float)
        device: (torch.device, str): Device where the tensor should be
            (Default value = 'cpu')
        requires_grad: bool): Trainable tensor or not? (Default value = False)

    Returns:
        (torch.Tensor): A tensor of appropriate dtype, device and
            requires_grad containing data

    """
    tt = (torch.as_tensor(data, dtype=dtype, device=device)
          .requires_grad_(requires_grad=requires_grad))
    return tt


def t(data, dtype=torch.float, device='cpu', requires_grad=False):
    """Convert a list or numpy array to torch tensor. If a torch tensor
    is passed it is cast to  dtype, device and the requires_grad flag is
    set. This always copies data.

    Args:
        data: (list, np.ndarray, torch.Tensor): Data to be converted to
            torch tensor.
        dtype: (torch.dtype): The type of the tensor elements
            (Default value = torch.float)
        device: (torch.device, str): Device where the tensor should be
            (Default value = 'cpu')
        requires_grad: (bool): Trainable tensor or not? (Default value = False)

    Returns:
        (torch.Tensor): A tensor of appropriate dtype, device and
            requires_grad containing data

    """
    tt = torch.tensor(data, dtype=dtype, device=device,
                      requires_grad=requires_grad)
    return tt


def mktensor(data, dtype=torch.float, device='cpu',
             requires_grad=False, copy=True):
    """Convert a list or numpy array to torch tensor. If a torch tensor
        is passed it is cast to  dtype, device and the requires_grad flag is
        set. This can copy data or make the operation in place.

    Args:
        data: (list, np.ndarray, torch.Tensor): Data to be converted to
            torch tensor.
        dtype: (torch.dtype): The type of the tensor elements
            (Default value = torch.float)
        device: (torch.device, str): Device where the tensor should be
            (Default value = 'cpu')
        requires_grad: (bool): Trainable tensor or not? (Default value = False)
        copy: (bool): If false creates the tensor inplace else makes a copy
            (Default value = True)

    Returns:
        (torch.Tensor): A tensor of appropriate dtype, device and
            requires_grad containing data

    """
    tensor_factory = t if copy else t_
    return tensor_factory(
        data, dtype=dtype, device=device, requires_grad=requires_grad)


def from_checkpoint(checkpoint_file, obj, map_location=None):
    if checkpoint_file is None:
        return obj

    if not _sysutil.is_file(checkpoint_file):
        LOGGER.warn(
            f'The checkpoint {checkpoint_file} you are trying to load '
            'does not exist. Continuing without loading...')
        return obj

    state_dict = torch.load(checkpoint_file,
                            map_location=map_location)
    obj.load_state_dict(state_dict)
    return obj
